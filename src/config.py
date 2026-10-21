"""Configuration, read from environment variables.

Credentials never live in the source tree: `.env.example` documents every
variable and `.env` (ignored by git) holds the real values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """A required setting is missing or malformed."""


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(
            f"Environment variable '{name}' is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable '{name}' must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class DatabaseConfig:
    server: str
    database: str
    user: str
    password: str
    driver: str
    trust_server_certificate: bool

    def connection_string(self, database: str | None = None) -> str:
        """Build an ODBC connection string.

        `database` overrides the configured one, which is how the pipeline
        reaches `master` to create the demo database on first run.
        """
        parts = [
            f"Driver={{{self.driver}}}",
            f"Server={self.server}",
            f"Database={database or self.database}",
            f"UID={self.user}",
            f"PWD={self.password}",
        ]
        if self.trust_server_certificate:
            # Driver 18 encrypts by default and the local container presents a
            # self-signed certificate. Only ever enable this for local work.
            parts.append("TrustServerCertificate=yes")
        return ";".join(parts) + ";"

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"DatabaseConfig(server={self.server!r}, database={self.database!r}, "
            f"user={self.user!r}, password='***', driver={self.driver!r})"
        )


@dataclass(frozen=True)
class PipelineConfig:
    database: DatabaseConfig | None
    input_dir: Path
    rejects_dir: Path
    batch_size: int


def load_config(require_database: bool = True) -> PipelineConfig:
    """Read the configuration, failing loudly when something is missing.

    A dry run never opens a connection, so it does not need credentials: that
    is what makes the pipeline runnable straight after cloning.
    """
    database = None
    if require_database:
        database = DatabaseConfig(
            server=_required("SQL_SERVER"),
            database=_required("SQL_DATABASE"),
            user=_required("SQL_USER"),
            password=_required("SQL_PASSWORD"),
            driver=os.getenv("SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
            trust_server_certificate=os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "no").lower()
            in {"1", "true", "yes"},
        )
    return PipelineConfig(
        database=database,
        input_dir=PROJECT_ROOT / os.getenv("INPUT_DIR", "data/incoming"),
        rejects_dir=PROJECT_ROOT / os.getenv("REJECTS_DIR", "rejects"),
        batch_size=_int("BATCH_SIZE", 500),
    )
