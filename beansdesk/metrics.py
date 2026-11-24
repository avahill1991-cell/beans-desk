"""Performance statistics.

Kept separate from the backtester so the journal can reuse exactly the same maths.
If the journal and the backtest disagree about what a profit factor is, the product
is lying to the user somewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Stats:
    trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    total_pnl: float
    max_drawdown: float
    return_pct: float

    def as_rows(self) -> list[tuple[str, str]]:
        return [
            ("Trades", str(self.trades)),
            ("Win rate", f"{self.win_rate:.1f}%"),
            ("Profit factor", f"{self.profit_factor:.2f}"),
            ("Expectancy / trade", f"${self.expectancy:.2f}"),
            ("Average win", f"${self.avg_win:.2f}"),
            ("Average loss", f"${self.avg_loss:.2f}"),
            ("Largest win", f"${self.largest_win:.2f}"),
            ("Largest loss", f"${self.largest_loss:.2f}"),
            ("Net P&L", f"${self.total_pnl:.2f}"),
            ("Max drawdown", f"${self.max_drawdown:.2f}"),
            ("Return", f"{self.return_pct:.2f}%"),
        ]


def max_drawdown(equity: Sequence[float]) -> float:
    """Largest peak-to-trough fall in dollars."""
    peak = float("-inf")
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def summarize(
    pnls: Iterable[float],
    start_equity: float = 2_000.0,
    equity_curve: Sequence[float] | None = None,
) -> Stats:
    pnl_list = [float(p) for p in pnls]
    trades = len(pnl_list)
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net = gross_profit - gross_loss

    if equity_curve is None:
        curve: list[float] = [start_equity]
        for p in pnl_list:
            curve.append(curve[-1] + p)
    else:
        curve = list(equity_curve)

    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    return Stats(
        trades=trades,
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / trades * 100.0) if trades else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        expectancy=(net / trades) if trades else 0.0,
        avg_win=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss=(sum(losses) / len(losses)) if losses else 0.0,
        largest_win=max(wins) if wins else 0.0,
        largest_loss=min(losses) if losses else 0.0,
        total_pnl=net,
        max_drawdown=max_drawdown(curve),
        return_pct=(net / start_equity * 100.0) if start_equity else 0.0,
    )
