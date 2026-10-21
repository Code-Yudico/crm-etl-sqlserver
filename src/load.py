"""Loading into SQL Server.

Two properties matter here. The load is *idempotent*: rerunning it for a date
replaces that date instead of duplicating it, which is what makes a failed
morning run safe to repeat. And it is *batched*: `fast_executemany` sends a
batch per round trip instead of a statement per row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import pyodbc

from .schemas import ReportSchema
from .validation import validate_table_name

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    table: str
    deleted: int = 0
    inserted: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


def ensure_tables(connection: pyodbc.Connection, schemas: tuple[ReportSchema, ...]) -> None:
    """Create any destination table that does not exist yet."""
    cursor = connection.cursor()
    for schema in schemas:
        cursor.execute(schema.ddl)
    connection.commit()
    logger.info("Destination tables verified")


def _to_native(value: Any) -> Any:
    """Convert a pandas/numpy scalar into something pyodbc can bind.

    pyodbc binds Python types; numpy scalars coming out of a DataFrame are
    rejected, and NaN has to become NULL rather than the float nan.
    """
    if value is None:
        return None
    if pd.isna(value):
        return None
    item = getattr(value, "item", None)
    return item() if callable(item) else value


def _records(df: pd.DataFrame) -> list[tuple]:
    return [
        tuple(_to_native(value) for value in row)
        for row in df.itertuples(index=False, name=None)
    ]


def _delete_existing(cursor: pyodbc.Cursor, table: str, dates: list) -> int:
    """Remove the rows this run is about to replace."""
    if not dates:
        return 0
    placeholders = ", ".join("?" for _ in dates)
    cursor.execute(f"DELETE FROM dbo.{table} WHERE report_date IN ({placeholders})", *dates)
    deleted = max(cursor.rowcount, 0)
    logger.info("  %s: %d existing row(s) removed for %d date(s)", table, deleted, len(dates))
    return deleted


def load_dataframe(
    connection: pyodbc.Connection,
    df: pd.DataFrame,
    schema: ReportSchema,
    batch_size: int = 500,
) -> LoadResult:
    """Replace the dates present in `df` with its contents."""
    table = validate_table_name(schema.table)
    result = LoadResult(table=table)

    if df is None or df.empty:
        logger.warning("  %s: nothing to load", table)
        return result

    cursor = connection.cursor()
    cursor.fast_executemany = True

    try:
        dates = sorted({d for d in df["report_date"].dropna().tolist()})
        result.deleted = _delete_existing(cursor, table, dates)

        columns = list(df.columns)
        column_list = ", ".join(f"[{column}]" for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        # The table name is whitelisted above; every value is bound.
        statement = f"INSERT INTO dbo.{table} ({column_list}) VALUES ({placeholders})"

        records = _records(df)
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            try:
                cursor.executemany(statement, batch)
                result.inserted += len(batch)
            except pyodbc.Error as exc:
                # One bad row fails its whole batch. Retrying the batch row by
                # row keeps the good rows and names the bad ones, instead of
                # losing the batch or the run.
                logger.warning(
                    "  %s: batch at offset %d failed (%s), retrying row by row",
                    table,
                    start,
                    exc,
                )
                for offset, record in enumerate(batch):
                    try:
                        cursor.execute(statement, record)
                        result.inserted += 1
                    except pyodbc.Error as row_exc:
                        result.failed += 1
                        result.failures.append(f"row {start + offset}: {row_exc}")

        connection.commit()
    except Exception:
        connection.rollback()
        logger.error("  %s: load rolled back", table)
        raise

    if result.failed:
        logger.warning("  %s: %d row(s) could not be inserted", table, result.failed)
    logger.info("  %s: %d row(s) inserted", table, result.inserted)
    return result
