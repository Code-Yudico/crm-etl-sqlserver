"""SQL Server connectivity.

The retry policy matters because this runs unattended early every morning: a
transient network or service hiccup should cost a few seconds, not the day's
report.
"""

from __future__ import annotations

import logging

import pyodbc
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import DatabaseConfig
from .validation import validate_identifier

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(pyodbc.Error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def connect(
    config: DatabaseConfig, database: str | None = None, autocommit: bool = False
) -> pyodbc.Connection:
    """Open a connection, retrying with exponential backoff."""
    return pyodbc.connect(config.connection_string(database), autocommit=autocommit)


def ensure_database(config: DatabaseConfig) -> None:
    """Create the destination database if this is the first run.

    The SQL Server image does not run initialisation scripts on startup, so the
    pipeline creates its own database. CREATE DATABASE cannot run inside a
    transaction, hence the autocommit connection, and a database name cannot be
    a query parameter, hence the identifier check.
    """
    name = validate_identifier(config.database, "database name")

    connection = connect(config, database="master", autocommit=True)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DB_ID(?)", name)
        if cursor.fetchone()[0] is None:
            logger.info("Creating database %r", name)
            cursor.execute(f"CREATE DATABASE [{name}]")
        else:
            logger.info("Database %r already exists", name)
    finally:
        connection.close()
