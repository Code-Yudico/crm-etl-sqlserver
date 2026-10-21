"""Generate a synthetic CRM export.

The real pipeline consumed a report exported by a call centre platform. This
script reproduces the *shape* of that report -- its headers, its quirks and its
data types -- with entirely invented content, so the pipeline can be run and
tested by anyone.

Quirks reproduced on purpose, because the transformation stage exists to deal
with them:

* Spanish headers with accents, percent signs, dots and spaces.
* Durations written as HH:MM:SS rather than as numbers.
* A "-" placeholder instead of an empty cell.
* A few malformed rows, so the reject path is exercised on every run.

    python scripts/generate_data.py --date 2026-10-19 --agents 40
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "incoming"

# Generic campaign types, of the sort any contact centre runs.
CAMPAIGNS = [
    (101, "Ventas"),
    (102, "Retencion"),
    (103, "Soporte Tecnico"),
    (104, "Cobranza"),
    (105, "Encuestas"),
]

# One row per agent per hour, which is how the source reported intervals.
INTERVAL_START_HOUR = 8
INTERVAL_COUNT = 10

BEHAVIOR_HEADERS = [
    "Agente", "Fecha", "ID", "Campaña",
    "In", "% In",
    "In Rechazadas/Ignoradas", "% In Rechazadas/Ignoradas",
    "In Atendidas", "% In Atendidas",
    "Out", "% Out",
    "Out Rechazadas/Ignoradas", "% Out Rechazadas/Ignoradas",
    "Out Atendidas", "% Out Atendidas",
    "Out Dialing", "% Out Dialing",
    "Llamados con Hold", "% Llamados con Hold",
    "Tiempo medio de respuesta IN", "Tiempo medio de respuesta OUT",
]

STATE_DURATION_HEADERS = [
    "T. Login", "T. Login Neto", "T. Available", "T. Preview", "T. Dialing",
    "T. Ringing", "T. Talking", "T. Talking In", "T. Talking Out", "T. Hold",
    "T. ACW", "T. Other CRM", "T. Pause",
]

STATE_HEADERS = (
    ["Fecha", "Intervalo", "ID", "Agente", "ID Campaña", "Campaña"]
    + STATE_DURATION_HEADERS
    + [f"T. Diario {header.removeprefix('T. ')}" for header in STATE_DURATION_HEADERS]
)


def as_clock(seconds: int) -> str:
    """Format a duration the way the source does: HH:MM:SS."""
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def pct(part: int, total: int) -> str:
    return f"{(part / total * 100):.2f}" if total else "0.00"


def build_agents(faker: Faker, count: int) -> list[dict]:
    return [
        {
            "id": 1000 + index,
            "name": faker.name(),
            "campaign": random.choice(CAMPAIGNS),
        }
        for index in range(count)
    ]


def behavior_rows(agents: list[dict], report_date: date) -> list[list]:
    rows = []
    for agent in agents:
        inbound = random.randint(20, 160)
        inbound_rejected = random.randint(0, inbound // 5)
        inbound_answered = inbound - inbound_rejected

        outbound = random.randint(10, 120)
        outbound_rejected = random.randint(0, outbound // 4)
        outbound_dialing = random.randint(0, outbound // 6)
        outbound_answered = outbound - outbound_rejected - outbound_dialing

        with_hold = random.randint(0, inbound_answered)

        rows.append([
            agent["name"],
            report_date.strftime("%d/%m/%Y"),
            agent["id"],
            agent["campaign"][1],
            inbound, pct(inbound, inbound),
            inbound_rejected, pct(inbound_rejected, inbound),
            inbound_answered, pct(inbound_answered, inbound),
            outbound, pct(outbound, outbound),
            outbound_rejected, pct(outbound_rejected, outbound),
            outbound_answered, pct(outbound_answered, outbound),
            outbound_dialing, pct(outbound_dialing, outbound),
            with_hold, pct(with_hold, inbound_answered or 1),
            as_clock(random.randint(5, 90)),
            as_clock(random.randint(5, 120)),
        ])
    return rows


def state_rows(agents: list[dict], report_date: date) -> list[list]:
    rows = []
    for agent in agents:
        running = [0] * len(STATE_DURATION_HEADERS)
        for index in range(INTERVAL_COUNT):
            start = datetime.combine(report_date, datetime.min.time()) + timedelta(
                hours=INTERVAL_START_HOUR + index
            )
            interval = f"{start:%H:%M} - {start + timedelta(hours=1):%H:%M}"

            login = random.randint(2400, 3600)
            net_login = login - random.randint(0, 300)
            talking_in = random.randint(0, int(net_login * 0.4))
            talking_out = random.randint(0, int(net_login * 0.3))
            talking = talking_in + talking_out
            hold = random.randint(0, 300)
            acw = random.randint(0, 420)
            preview = random.randint(0, 240)
            dialing = random.randint(0, 180)
            ringing = random.randint(0, 120)
            other_crm = random.randint(0, 300)
            pause = random.randint(0, 600)
            available = max(net_login - talking - hold - acw - pause, 0)

            current = [
                login, net_login, available, preview, dialing, ringing,
                talking, talking_in, talking_out, hold, acw, other_crm, pause,
            ]
            running = [total + value for total, value in zip(running, current)]

            rows.append(
                [
                    report_date.strftime("%d/%m/%Y"),
                    interval,
                    agent["id"],
                    agent["name"],
                    agent["campaign"][0],
                    agent["campaign"][1],
                ]
                + [as_clock(value) for value in current]
                + [as_clock(value) for value in running]
            )
    return rows


def add_malformed_rows(rows: list[list], headers: list[str]) -> list[list]:
    """Insert the kind of broken rows the real export produced.

    They are what the reject file is for: the pipeline should load everything
    else and say exactly which rows it could not use.
    """
    if len(rows) < 2:
        return rows

    missing_id = list(rows[0])
    missing_id[headers.index("ID")] = ""

    placeholder = list(rows[1])
    for index, header in enumerate(headers):
        if header.startswith(("Tiempo", "T.")):
            placeholder[index] = "-"
            break

    return rows + [missing_id, placeholder]


def write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"  {path.relative_to(PROJECT_ROOT)}  ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic CRM export.")
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        default=date.today() - timedelta(days=1),
        help="report date (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument("--agents", type=int, default=25, help="number of agents")
    parser.add_argument("--seed", type=int, default=42, help="seed, for reproducible output")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT, help="output directory")
    args = parser.parse_args()

    faker = Faker("es_MX")
    Faker.seed(args.seed)
    random.seed(args.seed)

    agents = build_agents(faker, args.agents)
    stamp = args.date.isoformat()

    print(f"Generating a synthetic export for {stamp} ({args.agents} agents):")
    write_csv(
        args.out / f"agent_behavior_{stamp}.csv",
        BEHAVIOR_HEADERS,
        add_malformed_rows(behavior_rows(agents, args.date), BEHAVIOR_HEADERS),
    )
    write_csv(
        args.out / f"agent_states_{stamp}.csv",
        STATE_HEADERS,
        add_malformed_rows(state_rows(agents, args.date), STATE_HEADERS),
    )


if __name__ == "__main__":
    main()
