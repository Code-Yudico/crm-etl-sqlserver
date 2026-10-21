"""Pipeline entry point: read the export, normalise it, load it.

Run with `python -m src.pipeline`. Add `--dry-run` to exercise extraction and
transformation without touching the database.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import db, extract, load
from .config import ConfigError, PipelineConfig, load_config
from .schemas import SCHEMAS
from .transform import TransformResult, transform_report

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging(verbose: bool = False) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_DIR / "etl.log", encoding="utf-8"),
        ],
    )


def write_rejects(result: TransformResult, name: str, rejects_dir: Path) -> Path | None:
    """Persist unusable rows so a failure can be explained the next morning."""
    if result.rejected.empty:
        return None
    rejects_dir.mkdir(parents=True, exist_ok=True)
    path = rejects_dir / f"{name}_rejects.csv"
    result.rejected.to_csv(path, index=False, encoding="utf-8")
    logger.warning("%s: %d rejected row(s) written to %s", name, result.rejected_count, path)
    return path


def run(config: PipelineConfig, dry_run: bool = False) -> int:
    started = time.time()
    logger.info("=" * 68)
    logger.info("CRM ETL - starting%s", " (dry run)" if dry_run else "")
    logger.info("Source: %s", config.input_dir)
    if not dry_run:
        logger.info("Destination: %s / %s", config.database.server, config.database.database)
    logger.info("=" * 68)

    # --- Extract -----------------------------------------------------------
    logger.info("STAGE 1: EXTRACT")
    source_files = extract.discover_source_files(config.input_dir)

    # --- Transform ---------------------------------------------------------
    logger.info("STAGE 2: TRANSFORM")
    transformed: list[tuple] = []
    total_rejected = 0
    for source in source_files:
        raw = extract.read_report(source.path)
        result = transform_report(raw, source.schema)
        write_rejects(result, source.schema.name, config.rejects_dir)
        total_rejected += result.rejected_count
        transformed.append((source.schema, result.clean))

    if all(frame.empty for _, frame in transformed):
        logger.error("No usable rows after transformation. Nothing to load.")
        return 1

    # --- Load --------------------------------------------------------------
    if dry_run:
        logger.info("STAGE 3: LOAD skipped (dry run)")
        for schema, frame in transformed:
            logger.info("  %s: %d row(s) would be loaded", schema.table, len(frame))
        logger.info("Finished in %.2fs", time.time() - started)
        return 0

    logger.info("STAGE 3: LOAD")
    db.ensure_database(config.database)
    connection = db.connect(config.database)
    results = []
    try:
        load.ensure_tables(connection, SCHEMAS)
        for schema, frame in transformed:
            results.append(load.load_dataframe(connection, frame, schema, config.batch_size))
    finally:
        connection.close()

    # --- Summary -----------------------------------------------------------
    logger.info("=" * 68)
    logger.info("CRM ETL - completed in %.2fs", time.time() - started)
    for result in results:
        logger.info("  %s: %d inserted, %d replaced, %d failed",
                    result.table, result.inserted, result.deleted, result.failed)
    if total_rejected:
        logger.info("  %d row(s) rejected, see %s", total_rejected, config.rejects_dir)
    logger.info("=" * 68)

    return 1 if any(result.failed for result in results) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CRM to SQL Server ETL")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run extraction and transformation only, without a database",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        config = load_config(require_database=not args.dry_run)
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    try:
        return run(config, dry_run=args.dry_run)
    except extract.ExtractionError as exc:
        logger.error("Extraction failed: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
