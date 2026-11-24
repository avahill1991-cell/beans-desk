"""The trade journal.

Same metric definitions as the backtester, on purpose. The point of the journal is
to catch the gap between the plan and the execution, so it also tracks whether the
plan was followed - that column is usually the most expensive one in the file.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from beansdesk.metrics import Stats, summarize

COLUMNS = [
    "Date",
    "Time_IL",
    "Contract",
    "Side",
    "EntryPrice",
    "ExitPrice",
    "Ticks",
    "Contracts",
    "PnL_USD",
    "PnL_ILS",
    "Setup",
    "Reason",
    "Sentiment(1-5)",
    "FollowedPlan(Y/N)",
    "Notes",
]

ILS_PER_USD = 3.6  # rough default; the UI should let the user set this


@dataclass
class JournalReport:
    stats: Stats
    rows: int
    followed_plan_pct: float
    avg_sentiment: float
    by_setup: dict[str, float]


def ensure_journal(path: str | Path) -> Path:
    p = Path(path)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(COLUMNS)
    return p


def append_trade(
    path: str | Path,
    *,
    when: datetime,
    contract: str,
    side: str,
    entry: float,
    exit: float,
    contracts: int = 1,
    tick_size: float = 0.00125,
    tick_value: float = 1.25,
    setup: str = "",
    reason: str = "",
    sentiment: int = 3,
    followed_plan: bool = True,
    notes: str = "",
) -> dict[str, str]:
    """Append one closed trade and return the row that was written."""
    p = ensure_journal(path)
    direction = 1 if side.lower() in ("long", "buy", "b") else -1
    ticks = (exit - entry) * direction / tick_size
    pnl = ticks * tick_value * contracts

    row = {
        "Date": when.date().isoformat(),
        "Time_IL": when.strftime("%H:%M"),
        "Contract": contract,
        "Side": side.upper(),
        "EntryPrice": f"{entry:.4f}",
        "ExitPrice": f"{exit:.4f}",
        "Ticks": f"{ticks:+.2f}",
        "Contracts": str(contracts),
        "PnL_USD": f"{pnl:+.2f}",
        "PnL_ILS": f"{pnl * ILS_PER_USD:+.2f}",
        "Setup": setup,
        "Reason": reason,
        "Sentiment(1-5)": str(sentiment),
        "FollowedPlan(Y/N)": "Y" if followed_plan else "N",
        "Notes": notes,
    }
    with p.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=COLUMNS).writerow(row)
    return row


def read_journal(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", newline="", encoding="utf-8-sig") as fh:
        return [row for row in csv.DictReader(fh) if (row.get("Date") or "").strip()]


def _to_float(raw: str | None, default: float = 0.0) -> float:
    try:
        return float((raw or "").replace("+", "").strip())
    except ValueError:
        return default


def analyse(path: str | Path, start_equity: float = 2_000.0) -> JournalReport:
    rows = read_journal(path)
    pnls = [_to_float(r.get("PnL_USD")) for r in rows]

    followed = [r for r in rows if (r.get("FollowedPlan(Y/N)") or "").strip().upper() in ("Y", "N")]
    followed_yes = [r for r in followed if (r.get("FollowedPlan(Y/N)") or "").strip().upper() == "Y"]
    sentiments = [
        _to_float(r.get("Sentiment(1-5)"), 0.0)
        for r in rows
        if (r.get("Sentiment(1-5)") or "").strip()
    ]

    by_setup: dict[str, float] = {}
    for row, pnl in zip(rows, pnls):
        key = (row.get("Setup") or "unlabelled").strip() or "unlabelled"
        by_setup[key] = by_setup.get(key, 0.0) + pnl

    return JournalReport(
        stats=summarize(pnls, start_equity),
        rows=len(rows),
        followed_plan_pct=(len(followed_yes) / len(followed) * 100.0) if followed else 0.0,
        avg_sentiment=(sum(sentiments) / len(sentiments)) if sentiments else 0.0,
        by_setup=dict(sorted(by_setup.items(), key=lambda kv: kv[1], reverse=True)),
    )
