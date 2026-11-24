"""Bar loading and validation.

Deliberately boring: a CSV in, a list of Bar out, every failure named with the
row number so a non-technical user can fix their own file.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

REQUIRED_COLUMNS = ("date", "open", "high", "low", "close")
OPTIONAL_COLUMNS = ("volume",)


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLC bar. `date` is the session date."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def range(self) -> float:
        return self.high - self.low


def _parse_date(raw: str) -> date:
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # ISO datetime, e.g. "2026-11-20 00:00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError as exc:
        raise ValueError(f"unrecognised date {raw!r}") from exc


def load_bars(path: str | Path) -> list[Bar]:
    """Load and validate an OHLC CSV.

    Raises:
        FileNotFoundError: the path does not exist.
        ValueError: a required column is missing, or a row is malformed.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"data file not found: {p}")

    bars: list[Bar] = []
    with p.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = [f.strip().lower() for f in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in fields]
        if missing:
            raise ValueError(
                f"{p.name}: missing column(s) {', '.join(missing)}. "
                f"Need at least: {', '.join(REQUIRED_COLUMNS)}"
            )
        reader.fieldnames = fields

        for line_no, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values()):
                continue  # blank line
            try:
                bar = Bar(
                    date=_parse_date(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{p.name} line {line_no}: {exc}") from exc

            if bar.high < bar.low:
                raise ValueError(f"{p.name} line {line_no}: high ({bar.high}) < low ({bar.low})")
            if not (bar.low <= bar.open <= bar.high) or not (bar.low <= bar.close <= bar.high):
                raise ValueError(f"{p.name} line {line_no}: open/close outside the high-low range")
            bars.append(bar)

    if not bars:
        raise ValueError(f"{p.name}: no data rows")

    bars.sort(key=lambda b: b.date)
    for prev, cur in zip(bars, bars[1:]):
        if prev.date == cur.date:
            raise ValueError(f"{p.name}: duplicate date {cur.date}")
    return bars
