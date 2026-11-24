"""A small, deterministic backtester with three strategies and honest costs.

Three things matter more than features here:

1. **No lookahead.** A signal computed on bar *i* is filled at the close of bar *i*,
   and can only be stopped or targeted from bar *i+1* onward.
2. **Honest tie-breaking.** If a bar touches both the stop and the target, the stop
   is assumed to fill first. Results lean pessimistic, which is the only direction a
   backtest is allowed to be wrong in.
3. **Costs are always on.** Commission per side and slippage in ticks are part of the
   config, not an option. A backtest without friction is a fantasy with a chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from beansdesk.data import Bar
from beansdesk.metrics import Stats, summarize
from beansdesk.risk import Side

STRATEGIES = ("sma", "breakout", "seasonal")


@dataclass(frozen=True)
class BacktestConfig:
    strategy: str = "sma"

    # sma
    fast: int = 10
    slow: int = 30

    # breakout
    lookback: int = 20

    # seasonal
    entry_month: int = 5
    entry_day: int = 15
    exit_month: int = 7
    exit_day: int = 20

    # exits
    stop_ticks: int = 4
    reward_risk: float = 2.0

    # contract + account
    tick_size: float = 0.00125
    tick_value: float = 1.25
    contracts: int = 1
    start_equity: float = 2_000.0

    # friction
    commission_per_side: float = 1.0
    slippage_ticks: float = 0.5

    def __post_init__(self) -> None:
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {self.strategy!r}; choose from {', '.join(STRATEGIES)}")
        if self.fast < 1 or self.slow < 2:
            raise ValueError("fast must be >= 1 and slow >= 2")
        if self.fast >= self.slow:
            raise ValueError("fast period must be shorter than slow period")
        if self.lookback < 2:
            raise ValueError("lookback must be at least 2")
        if self.stop_ticks < 1:
            raise ValueError("stop_ticks must be at least 1")
        if self.reward_risk <= 0:
            raise ValueError("reward_risk must be positive")
        if self.contracts < 1:
            raise ValueError("contracts must be at least 1")
        if self.commission_per_side < 0:
            raise ValueError("commission_per_side cannot be negative")
        if self.slippage_ticks < 0:
            raise ValueError("slippage_ticks cannot be negative")

    @property
    def label(self) -> str:
        if self.strategy == "sma":
            return f"{self.fast}/{self.slow} SMA"
        if self.strategy == "breakout":
            return f"{self.lookback}-bar breakout"
        return (
            f"seasonal {self.entry_month:02d}-{self.entry_day:02d}"
            f" to {self.exit_month:02d}-{self.exit_day:02d}"
        )

    @property
    def warmup(self) -> int:
        return {"sma": self.slow, "breakout": self.lookback, "seasonal": 1}[self.strategy]

    @property
    def round_turn_cost(self) -> float:
        return self.commission_per_side * 2 * self.contracts


@dataclass(frozen=True)
class Trade:
    entry_date: date
    exit_date: date
    side: Side
    entry: float          # the signal bar's close, before slippage
    fill: float           # what we actually paid or received
    exit: float
    stop: float
    target: float
    ticks: float          # gross move in ticks, fill to exit
    gross: float          # ticks * tick_value * contracts
    costs: float          # commission + slippage, in dollars
    pnl: float            # gross - costs
    reason: str

    @property
    def won(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity: list[float]
    stats: Stats
    config: BacktestConfig
    bars: list[Bar]


def _sma(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def _in_season(day: date, cfg: BacktestConfig) -> bool:
    start = (cfg.entry_month, cfg.entry_day)
    end = (cfg.exit_month, cfg.exit_day)
    today = (day.month, day.day)
    if start <= end:
        return start <= today < end
    return today >= start or today < end


def _signals(bars: Sequence[Bar], cfg: BacktestConfig) -> list[tuple[int, Side]]:
    """Every point where the strategy says 'open here'. One signal per crossing."""
    n = len(bars)
    out: list[tuple[int, Side]] = []

    if cfg.strategy == "sma":
        closes = [b.close for b in bars]
        fast, slow = _sma(closes, cfg.fast), _sma(closes, cfg.slow)
        for i in range(max(cfg.slow, 1), n):
            if None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
                continue
            if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:  # type: ignore[operator]
                out.append((i, Side.LONG))
            elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:  # type: ignore[operator]
                out.append((i, Side.SHORT))

    elif cfg.strategy == "breakout":
        for i in range(cfg.lookback, n):
            window = bars[i - cfg.lookback : i]
            high = max(b.high for b in window)
            low = min(b.low for b in window)
            if bars[i].close > high:
                out.append((i, Side.LONG))
            elif bars[i].close < low:
                out.append((i, Side.SHORT))

    else:  # seasonal
        for i in range(1, n):
            if _in_season(bars[i].date, cfg) and not _in_season(bars[i - 1].date, cfg):
                out.append((i, Side.LONG))

    return out


def run_backtest(bars: Sequence[Bar], config: BacktestConfig | None = None) -> BacktestResult:
    cfg = config or BacktestConfig()
    bars = list(bars)
    if len(bars) < cfg.warmup + 2:
        raise ValueError(
            f"need at least {cfg.warmup + 2} bars for a {cfg.strategy} backtest, got {len(bars)}"
        )

    slip = cfg.slippage_ticks * cfg.tick_size
    trades: list[Trade] = []
    equity: list[float] = [cfg.start_equity]
    blocked_until = -1

    for index, side in _signals(bars, cfg):
        if index <= blocked_until or index >= len(bars) - 1:
            continue

        raw_entry = bars[index].close
        fill = raw_entry + slip if side is Side.LONG else raw_entry - slip
        distance = cfg.stop_ticks * cfg.tick_size
        if side is Side.LONG:
            stop, target = fill - distance, fill + distance * cfg.reward_risk
        else:
            stop, target = fill + distance, fill - distance * cfg.reward_risk

        exit_index = len(bars) - 1
        exit_price = bars[exit_index].close
        reason = "end of data"

        for j in range(index + 1, len(bars)):
            bar = bars[j]

            if cfg.strategy == "seasonal" and not _in_season(bar.date, cfg):
                exit_index, exit_price, reason = j, bar.close, "season end"
                break

            if side is Side.LONG:
                hit_stop, hit_target = bar.low <= stop, bar.high >= target
            else:
                hit_stop, hit_target = bar.high >= stop, bar.low <= target

            if hit_stop:            # ties go to the stop, always
                exit_index = j
                exit_price = stop - slip if side is Side.LONG else stop + slip
                reason = "stop"
                break
            if hit_target:
                exit_index, exit_price, reason = j, target, "target"
                break

        # Raw exit before slippage, so gross - costs == pnl exactly.
        raw_exit = exit_price if reason in ("stop", "target") else bars[exit_index].close
        direction = 1 if side is Side.LONG else -1
        ticks = (raw_exit - raw_entry) * direction / cfg.tick_size
        gross = ticks * cfg.tick_value * cfg.contracts

        slippage_cost = 2 * cfg.slippage_ticks * cfg.tick_value * cfg.contracts
        costs = cfg.round_turn_cost + slippage_cost
        net = gross - costs

        trades.append(
            Trade(
                entry_date=bars[index].date,
                exit_date=bars[exit_index].date,
                side=side,
                entry=raw_entry,
                fill=fill,
                exit=exit_price,
                stop=stop,
                target=target,
                ticks=ticks,
                gross=gross,
                costs=costs,
                pnl=net,
                reason=reason,
            )
        )
        equity.append(equity[-1] + net)
        blocked_until = exit_index

    stats = summarize([t.pnl for t in trades], cfg.start_equity, equity)
    return BacktestResult(trades=trades, equity=equity, stats=stats, config=cfg, bars=bars)
