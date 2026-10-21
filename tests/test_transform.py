"""Tests for the normalisation stage.

These run without a database: the transformation is where the logic lives, so
it is the part worth pinning down.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.schemas import AGENT_BEHAVIOR, AGENT_OPERATIONAL_STATES
from src.transform import (
    clean_column_name,
    coerce_durations,
    duration_to_minutes,
    transform_report,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Agente", "agente"),
        ("Campaña", "campana"),
        ("% In Atendidas", "pct_in_atendidas"),
        ("In Rechazadas/Ignoradas", "in_rechazadas_ignoradas"),
        ("T. Login Neto", "t_login_neto"),
        ("T. Diario Other CRM", "t_diario_other_crm"),
        ("  Tiempo medio de respuesta IN  ", "tiempo_medio_de_respuesta_in"),
        ("ID Campaña", "id_campana"),
    ],
)
def test_clean_column_name(raw: str, expected: str) -> None:
    assert clean_column_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01:30:00", 90.0),
        ("00:00:30", 0.5),
        ("02:15", 135.0),
        ("12.5", 12.5),
        ("-", 0.0),
        ("", 0.0),
        (None, 0.0),
        ("not a time", 0.0),
    ],
)
def test_duration_to_minutes(raw: object, expected: float) -> None:
    assert duration_to_minutes(raw) == pytest.approx(expected)


def test_coerce_durations_handles_already_numeric_columns() -> None:
    df = pd.DataFrame({"login_time": [15.5, 20.0, None]})
    result = coerce_durations(df, ("login_time",))
    assert result["login_time"].tolist() == [15.5, 20.0, 0.0]


def _behavior_export() -> pd.DataFrame:
    """A minimal export: the headers the source really emits."""
    return pd.DataFrame(
        {
            "Agente": ["Ana Ruiz", "Luis Mora", "Sin ID"],
            "Fecha": ["19/10/2026", "19/10/2026", "19/10/2026"],
            "ID": ["1001", "1002", ""],
            "Campaña": ["Ventas", "Cobranza", "Ventas"],
            "In": ["40", "30", "10"],
            "% In": ["100.00", "100.00", "100.00"],
            "In Atendidas": ["38", "29", "9"],
            "Tiempo medio de respuesta IN": ["00:01:30", "-", "00:02:00"],
        }
    )


def test_transform_renames_reserved_words_and_converts_types() -> None:
    result = transform_report(_behavior_export(), AGENT_BEHAVIOR)
    clean = result.clean

    # "in" is a reserved word in T-SQL, so the column is renamed on the way in.
    assert "in" not in clean.columns
    assert clean["inbound_total"].tolist() == [40, 30]
    assert clean["inbound_total"].dtype.kind == "i"

    # HH:MM:SS becomes decimal minutes, and "-" becomes zero.
    assert clean["avg_response_time_inbound"].tolist() == [1.5, 0.0]

    assert str(clean["report_date"].iloc[0]) == "2026-10-19"


def test_transform_rejects_rows_without_an_agent_id() -> None:
    result = transform_report(_behavior_export(), AGENT_BEHAVIOR)

    assert result.rejected_count == 1
    assert result.rejected["agent"].tolist() == ["Sin ID"]
    assert "missing agent_id" in result.rejected["reject_reason"].iloc[0]

    # The usable rows still load: one bad row does not cost the run.
    assert len(result.clean) == 2
    # A missing id must never be loaded as agent 0.
    assert 0 not in result.clean["agent_id"].tolist()


def test_transform_fills_columns_the_export_omitted() -> None:
    result = transform_report(_behavior_export(), AGENT_BEHAVIOR)

    assert list(result.clean.columns) == AGENT_BEHAVIOR.final_columns
    # Absent from the export, present in the table, defaulted to zero.
    assert result.clean["outbound_total"].tolist() == [0, 0]


def test_transform_operational_states_maps_every_duration() -> None:
    export = pd.DataFrame(
        {
            "Fecha": ["19/10/2026"],
            "Intervalo": ["08:00 - 09:00"],
            "ID": ["1001"],
            "Agente": ["Ana Ruiz"],
            "ID Campaña": ["101"],
            "Campaña": ["Ventas"],
            "T. Login": ["01:00:00"],
            "T. Talking In": ["00:20:00"],
            "T. Diario Login": ["03:00:00"],
        }
    )

    result = transform_report(export, AGENT_OPERATIONAL_STATES)
    row = result.clean.iloc[0]

    assert result.rejected_count == 0
    assert row["login_time"] == pytest.approx(60.0)
    assert row["talking_inbound_time"] == pytest.approx(20.0)
    assert row["daily_login_time"] == pytest.approx(180.0)
    # "interval" is reserved in the SQL grammar, so it is stored renamed.
    assert "time_interval" in result.clean.columns
    assert row["campaign_id"] == 101
