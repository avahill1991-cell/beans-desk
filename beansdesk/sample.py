"""Synthetic OHLC data shaped like the user's journal prices.

Only for trying the tool. Never for a real backtest.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path


def generate(
    path: str | Path,
    bars: int = 520,
    seed: int = 7,
    start: float = 12.40,
    cycle_period: float = 14.0,
    cycle_amp: float = 0.002,
    noise: float = 0.0025,
    wick_scale: float = 0.0032,
    drift_scale: float = 0.45,
) -> Path:
    rng = random.Random(seed)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    price = start
    day = date(2024, 1, 2)
    rows = []

    for i in range(bars):
        while day.weekday() >= 5:            # skip weekends
            day += timedelta(days=1)

        cycle = math.sin(i / cycle_period) * cycle_amp   # slow seasonal trend
        shock = rng.gauss(0, noise)                      # daily noise
        drift = cycle * drift_scale + shock

        open_ = price
        close = max(0.5, price + drift)
        wick = abs(rng.gauss(0, wick_scale))
        high = max(open_, close) + wick
        low = max(0.05, min(open_, close) - wick)
        volume = rng.randint(800, 9000)

        rows.append(
            {
                "date": day.isoformat(),
                "open": f"{open_:.4f}",
                "high": f"{high:.4f}",
                "low": f"{low:.4f}",
                "close": f"{close:.4f}",
                "volume": volume,
            }
        )
        price = close
        day += timedelta(days=1)

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    return out
