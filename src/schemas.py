"""Schema definitions for every report handled by the pipeline.

Each report is described once, in a single `ReportSchema`, and every stage of
the pipeline (extract, transform, load) reads from that description. Adding a
new report means adding a schema here, not touching the pipeline.

The source system exports Spanish headers with accents, percent signs and
spaces ("% In Atendidas", "T. Login", "Campana" with a tilde). They are
normalised by `transform.clean_column_name` before the mapping below is
applied, so the keys are the *cleaned* source names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportSchema:
    """Everything the pipeline needs to know about one report."""

    name: str
    """Internal identifier, also used to recognise the source file."""

    table: str
    """Destination table in SQL Server."""

    filename_keywords: tuple[str, ...]
    """Lowercase fragments that identify this report in a file name."""

    column_mapping: dict[str, str]
    """Cleaned source column name -> destination column name."""

    integer_columns: tuple[str, ...] = ()
    percentage_columns: tuple[str, ...] = ()
    duration_columns: tuple[str, ...] = ()
    """Columns exported as HH:MM:SS that are stored as decimal minutes."""

    required_columns: tuple[str, ...] = ()
    """Rows missing any of these are rejected instead of loaded."""

    ddl: str = ""

    @property
    def final_columns(self) -> list[str]:
        """Destination columns, in the order they are inserted."""
        return list(self.column_mapping.values())


# ---------------------------------------------------------------------------
# Agent behaviour: one row per agent and day, with call counters.
# ---------------------------------------------------------------------------

# "in" and "out" are reserved words in T-SQL, so the source columns of the same
# name are renamed rather than quoted.
_BEHAVIOR_MAPPING = {
    "agente": "agent",
    "fecha": "report_date",
    "id": "agent_id",
    "campana": "campaign",
    "in": "inbound_total",
    "pct_in": "inbound_pct",
    "in_rechazadas_ignoradas": "inbound_rejected",
    "pct_in_rechazadas_ignoradas": "inbound_rejected_pct",
    "in_atendidas": "inbound_answered",
    "pct_in_atendidas": "inbound_answered_pct",
    "out": "outbound_total",
    "pct_out": "outbound_pct",
    "out_rechazadas_ignoradas": "outbound_rejected",
    "pct_out_rechazadas_ignoradas": "outbound_rejected_pct",
    "out_atendidas": "outbound_answered",
    "pct_out_atendidas": "outbound_answered_pct",
    "out_dialing": "outbound_dialing",
    "pct_out_dialing": "outbound_dialing_pct",
    "llamados_con_hold": "calls_with_hold",
    "pct_llamados_con_hold": "calls_with_hold_pct",
    "tiempo_medio_de_respuesta_in": "avg_response_time_inbound",
    "tiempo_medio_de_respuesta_out": "avg_response_time_outbound",
}

AGENT_BEHAVIOR = ReportSchema(
    name="agent_behavior",
    table="agent_behavior",
    filename_keywords=("behavior", "behaviour"),
    column_mapping=_BEHAVIOR_MAPPING,
    integer_columns=(
        "agent_id",
        "inbound_total",
        "inbound_rejected",
        "inbound_answered",
        "outbound_total",
        "outbound_rejected",
        "outbound_answered",
        "outbound_dialing",
        "calls_with_hold",
    ),
    percentage_columns=tuple(c for c in _BEHAVIOR_MAPPING.values() if c.endswith("_pct")),
    duration_columns=("avg_response_time_inbound", "avg_response_time_outbound"),
    required_columns=("agent_id", "report_date"),
    ddl="""
IF OBJECT_ID('dbo.agent_behavior', 'U') IS NULL
CREATE TABLE dbo.agent_behavior (
    agent NVARCHAR(200),
    report_date DATE,
    agent_id INT,
    campaign NVARCHAR(150),
    inbound_total INT,
    inbound_pct FLOAT,
    inbound_rejected INT,
    inbound_rejected_pct FLOAT,
    inbound_answered INT,
    inbound_answered_pct FLOAT,
    outbound_total INT,
    outbound_pct FLOAT,
    outbound_rejected INT,
    outbound_rejected_pct FLOAT,
    outbound_answered INT,
    outbound_answered_pct FLOAT,
    outbound_dialing INT,
    outbound_dialing_pct FLOAT,
    calls_with_hold INT,
    calls_with_hold_pct FLOAT,
    avg_response_time_inbound FLOAT,
    avg_response_time_outbound FLOAT,
    load_date DATETIME DEFAULT GETDATE()
);
""",
)


# ---------------------------------------------------------------------------
# Operational states: one row per agent and time interval, with durations.
# ---------------------------------------------------------------------------

# Every duration is exported as HH:MM:SS and stored as decimal minutes, which
# is what makes averages and sums usable from BI tools.
_STATE_DURATIONS = {
    "t_login": "login_time",
    "t_login_neto": "net_login_time",
    "t_available": "available_time",
    "t_preview": "preview_time",
    "t_dialing": "dialing_time",
    "t_ringing": "ringing_time",
    "t_talking": "talking_time",
    "t_talking_in": "talking_inbound_time",
    "t_talking_out": "talking_outbound_time",
    "t_hold": "hold_time",
    "t_acw": "acw_time",
    "t_other_crm": "other_crm_time",
    "t_pause": "pause_time",
}

# The source repeats every duration as a running daily total.
_STATE_DAILY_DURATIONS = {
    f"t_diario_{source.removeprefix('t_')}": f"daily_{target}"
    for source, target in _STATE_DURATIONS.items()
}

# "interval" is a reserved word in the ODBC/SQL-92 grammar, so it is renamed.
_STATE_MAPPING = {
    "fecha": "report_date",
    "intervalo": "time_interval",
    "id": "agent_id",
    "agente": "agent",
    "id_campana": "campaign_id",
    "campana": "campaign",
    **_STATE_DURATIONS,
    **_STATE_DAILY_DURATIONS,
}

_STATE_DURATION_COLUMNS = tuple(_STATE_DURATIONS.values()) + tuple(
    _STATE_DAILY_DURATIONS.values()
)

AGENT_OPERATIONAL_STATES = ReportSchema(
    name="agent_operational_states",
    table="agent_operational_states",
    filename_keywords=("states", "operational"),
    column_mapping=_STATE_MAPPING,
    integer_columns=("agent_id", "campaign_id"),
    duration_columns=_STATE_DURATION_COLUMNS,
    required_columns=("agent_id", "report_date"),
    ddl="""
IF OBJECT_ID('dbo.agent_operational_states', 'U') IS NULL
CREATE TABLE dbo.agent_operational_states (
    report_date DATE,
    time_interval NVARCHAR(50),
    agent_id INT,
    agent NVARCHAR(200),
    campaign_id INT,
    campaign NVARCHAR(150),
"""
    + "\n".join(f"    {column} FLOAT," for column in _STATE_DURATION_COLUMNS)
    + """
    load_date DATETIME DEFAULT GETDATE()
);
""",
)


SCHEMAS: tuple[ReportSchema, ...] = (AGENT_BEHAVIOR, AGENT_OPERATIONAL_STATES)

ALLOWED_TABLES: frozenset[str] = frozenset(schema.table for schema in SCHEMAS)
"""Whitelist of tables the loader may write to. See `validation`."""
