"""Normalisation of the raw CRM export into the destination schema.

The source is a report built for humans: accented headers, percentages as
text, durations as HH:MM:SS. The destination is a table meant to be queried,
so every value is converted to something SQL can aggregate.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from .schemas import ReportSchema

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransformResult:
    """Rows ready to load, plus the rows that could not be used."""

    clean: pd.DataFrame
    rejected: pd.DataFrame

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def clean_column_name(name: str) -> str:
    """Normalise one exported header into a SQL-friendly identifier.

    "% In Atendidas" -> "pct_in_atendidas"
    "Campana" (with a tilde) -> "campana"
    "T. Login Neto" -> "t_login_neto"
    """
    if not isinstance(name, str):
        return str(name)

    # Decompose accents and drop the combining marks: a-acute -> a, enye -> n.
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ASCII", "ignore").decode("ASCII")

    # A leading percent sign carries meaning, so it becomes a prefix instead of
    # being dropped with the other punctuation.
    name = re.sub(r"%\s*", "pct_", name)

    name = re.sub(r"[^a-zA-Z0-9]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name.lower()


def duration_to_minutes(value: object) -> float:
    """Convert an exported duration to decimal minutes.

    Accepts HH:MM:SS, HH:MM and plain numbers. Anything unparseable, empty or
    marked with the source's "-" placeholder becomes 0.0, which is what the
    report itself means by a blank cell.
    """
    if pd.isna(value) or str(value).strip() in {"-", "", "nan", "None"}:
        return 0.0

    text = str(value).strip()
    try:
        if ":" in text:
            parts = [int(part) for part in text.split(":")]
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return float(hours * 60 + minutes + seconds / 60)
            if len(parts) == 2:
                hours, minutes = parts
                return float(hours * 60 + minutes)
            return 0.0
        return float(text)
    except (ValueError, TypeError):
        return 0.0


def coerce_durations(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Convert duration columns to decimal minutes.

    Some exports deliver these columns already numeric, so the format is
    detected per column instead of assumed.
    """
    for column in columns:
        if column not in df.columns:
            continue
        looks_like_clock = df[column].astype(str).str.contains(":", na=False).any()
        if looks_like_clock:
            df[column] = df[column].apply(duration_to_minutes)
        else:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def coerce_integers(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
    return df


def coerce_floats(df: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return df


def _reject_reasons(df: pd.DataFrame, required: tuple[str, ...]) -> pd.Series:
    """One reason string per row; empty where the row is usable."""
    reasons = pd.Series("", index=df.index, dtype="object")
    for column in required:
        if column not in df.columns:
            reasons = reasons.str.cat(pd.Series(f"missing column {column}", index=df.index), sep="; ")
            continue
        missing = df[column].isna()
        reasons[missing] = reasons[missing].str.cat(
            pd.Series(f"missing {column}", index=df.index)[missing], sep="; "
        )
    return reasons.str.strip("; ")


def transform_report(raw: pd.DataFrame, schema: ReportSchema) -> TransformResult:
    """Apply `schema` to a raw export and split usable rows from rejects."""
    df = raw.copy()
    df.columns = [clean_column_name(column) for column in df.columns]
    df = df.rename(columns=schema.column_mapping)

    # A report may omit optional columns entirely; the table still has them.
    for column in schema.final_columns:
        if column not in df.columns:
            df[column] = None
    df = df[schema.final_columns]

    if "report_date" in df.columns:
        # The source writes dates as DD/MM/YYYY.
        df["report_date"] = pd.to_datetime(
            df["report_date"], errors="coerce", dayfirst=True
        ).dt.date

    # Required columns are checked *before* the numeric coercion below, which
    # fills blanks with zero: a row with no agent id must be rejected, not
    # silently loaded as agent 0.
    for column in schema.required_columns:
        if column in schema.integer_columns and column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    reasons = _reject_reasons(df, schema.required_columns)
    is_rejected = reasons.astype(bool)

    rejected = df[is_rejected].copy()
    if not rejected.empty:
        rejected["reject_reason"] = reasons[is_rejected]
        logger.warning(
            "%s: %d row(s) rejected before load", schema.name, len(rejected)
        )

    clean = df[~is_rejected].copy()
    clean = coerce_integers(clean, schema.integer_columns)
    clean = coerce_floats(clean, schema.percentage_columns)
    clean = coerce_durations(clean, schema.duration_columns)

    logger.info("%s: %d row(s) ready to load", schema.name, len(clean))
    return TransformResult(clean=clean, rejected=rejected)
