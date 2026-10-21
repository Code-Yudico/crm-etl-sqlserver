"""Tests for the guards that sit in front of the database."""

from __future__ import annotations

import pytest

from src.schemas import AGENT_BEHAVIOR, AGENT_OPERATIONAL_STATES
from src.validation import (
    TableNotAllowedError,
    validate_identifier,
    validate_table_name,
)


@pytest.mark.parametrize(
    "table", [AGENT_BEHAVIOR.table, AGENT_OPERATIONAL_STATES.table]
)
def test_known_tables_are_allowed(table: str) -> None:
    assert validate_table_name(table) == table


@pytest.mark.parametrize(
    "table",
    [
        "agent_behavior; DROP TABLE agent_behavior--",
        "sys.tables",
        "dbo.agent_behavior",
        "AGENT_BEHAVIOR",
        "",
    ],
)
def test_unknown_tables_are_rejected(table: str) -> None:
    """The table name is interpolated into the INSERT, so it is whitelisted.

    Values are always bound as parameters; the table name cannot be, which is
    exactly why it is checked against a fixed set rather than escaped.
    """
    with pytest.raises(TableNotAllowedError):
        validate_table_name(table)


@pytest.mark.parametrize("name", ["crm_etl_demo", "Reporting", "_staging", "db2"])
def test_valid_identifiers_pass(name: str) -> None:
    assert validate_identifier(name) == name


@pytest.mark.parametrize(
    "name",
    ["2db", "my db", "db];DROP DATABASE x--", "db-name", "", "dbo.db"],
)
def test_invalid_identifiers_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(name)
