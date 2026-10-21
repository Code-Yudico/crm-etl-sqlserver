"""Guards applied before anything reaches the database."""

from __future__ import annotations

import re

from .schemas import ALLOWED_TABLES


class TableNotAllowedError(ValueError):
    """A table name outside the whitelist was passed to the loader."""


def validate_table_name(table: str) -> str:
    """Return `table` if it is a known destination, raise otherwise.

    Table names cannot be passed as query parameters, so they end up
    interpolated into the INSERT statement. Checking them against a fixed
    whitelist is what keeps that interpolation safe: an attacker-controlled or
    simply mistaken name never reaches the server.
    """
    if table not in ALLOWED_TABLES:
        raise TableNotAllowedError(
            f"Table {table!r} is not a known destination. "
            f"Allowed tables: {sorted(ALLOWED_TABLES)}"
        )
    return table


# A deliberately narrow definition: letters, digits and underscores, not
# starting with a digit. Anything else is rejected rather than escaped.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str, kind: str = "identifier") -> str:
    """Return `value` if it is a safe SQL identifier, raise otherwise.

    Used for the few names that cannot be passed as query parameters, such as
    the database name in CREATE DATABASE.
    """
    if not _IDENTIFIER.match(value or ""):
        raise ValueError(f"Invalid {kind}: {value!r}")
    return value
