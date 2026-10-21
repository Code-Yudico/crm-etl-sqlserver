"""Reading the daily CRM export.

In production this step pulled the report out of the CRM's web front end. The
public version reads the same report from a CSV drop folder, which keeps the
rest of the pipeline identical and makes the project runnable by anyone. See
`scripts/generate_data.py` for the synthetic export.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .schemas import SCHEMAS, ReportSchema

logger = logging.getLogger(__name__)

# The export's encoding depends on who generated it, so the likely ones are
# tried in order rather than assumed.
ENCODINGS = ("utf-8-sig", "utf-8", "latin-1", "cp1252")


class ExtractionError(RuntimeError):
    """The source file could not be read."""


@dataclass(frozen=True)
class SourceFile:
    path: Path
    schema: ReportSchema


def identify_schema(filename: str) -> ReportSchema | None:
    """Match a file name against the known reports."""
    lowered = filename.lower()
    for schema in SCHEMAS:
        if any(keyword in lowered for keyword in schema.filename_keywords):
            return schema
    return None


def discover_source_files(input_dir: Path) -> list[SourceFile]:
    """List the recognised reports sitting in the drop folder."""
    if not input_dir.is_dir():
        raise ExtractionError(
            f"Input directory {input_dir} does not exist. "
            f"Run scripts/generate_data.py first."
        )

    found: list[SourceFile] = []
    for path in sorted(input_dir.glob("*.csv")):
        schema = identify_schema(path.name)
        if schema is None:
            logger.warning("Skipping unrecognised file: %s", path.name)
            continue
        found.append(SourceFile(path=path, schema=schema))

    if not found:
        raise ExtractionError(f"No recognised report found in {input_dir}")
    return found


def read_report(path: Path) -> pd.DataFrame:
    """Read one exported report into a DataFrame."""
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            # sep=None lets the python engine sniff comma vs semicolon, which
            # differ between exports depending on the regional settings.
            df = pd.read_csv(path, encoding=encoding, sep=None, engine="python")
            logger.info("Read %s (%d rows, %d columns, %s)", path.name, len(df), len(df.columns), encoding)
            return df.dropna(how="all")
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:  # malformed file: no other encoding will help
            raise ExtractionError(f"Could not read {path.name}: {exc}") from exc

    raise ExtractionError(f"Could not decode {path.name} with any of {ENCODINGS}: {last_error}")
