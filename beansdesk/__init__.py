"""Beans Desk - a risk-first trading desk.

The public surface is intentionally small:

    from beansdesk import load_bars, RiskPolicy, DayState, evaluate, run_backtest

Everything else is an implementation detail and may move.
"""

from beansdesk.data import Bar, load_bars
from beansdesk.risk import DayState, Decision, RiskPolicy, evaluate
from beansdesk.backtest import BacktestConfig, Trade, run_backtest
from beansdesk.metrics import summarize

__version__ = "0.2.0"

__all__ = [
    "Bar",
    "load_bars",
    "RiskPolicy",
    "DayState",
    "Decision",
    "evaluate",
    "BacktestConfig",
    "Trade",
    "run_backtest",
    "summarize",
    "__version__",
]
