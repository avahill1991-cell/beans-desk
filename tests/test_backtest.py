"""Backtester and metrics invariants.

The tests here are about honesty, not accuracy: no lookahead, deterministic output,
and a pessimistic tie-break.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from beansdesk.backtest import BacktestConfig, run_backtest
from beansdesk.data import Bar, load_bars
from beansdesk.metrics import max_drawdown, summarize
from beansdesk.sample import generate


def bars_from(prices: list[float], start: date = date(2024, 1, 1)) -> list[Bar]:
    out = []
    for i, price in enumerate(prices):
        out.append(
            Bar(
                date=start + timedelta(days=i),
                open=price,
                high=price + 0.002,
                low=price - 0.002,
                close=price,
            )
        )
    return out


class TieBreakTests(unittest.TestCase):
    def test_bar_touching_stop_and_target_counts_as_stop(self):
        prices = [10.0] * 6 + [10.2, 10.4, 10.6, 10.8]
        bars = bars_from(prices)

        # One bar that hits both sides of the trade.
        bars[7] = Bar(date=bars[7].date, open=10.4, high=30.0, low=0.0, close=10.4)

        cfg = BacktestConfig(
            fast=2, slow=4, stop_ticks=4, reward_risk=2.0, tick_size=0.00125, tick_value=1.25
        )
        result = run_backtest(bars, cfg)

        self.assertEqual(len(result.trades), 1, "expected exactly one trade")
        trade = result.trades[0]
        self.assertEqual(trade.reason, "stop", "ties must resolve as a stop fill")
        self.assertLess(trade.pnl, 0)
        self.assertAlmostEqual(trade.entry, 10.2)


class NoLookaheadTests(unittest.TestCase):
    def test_entry_price_is_the_signal_bar_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate(Path(tmp) / "sample.csv", bars=300, seed=11)
            bars = load_bars(path)
        result = run_backtest(bars, BacktestConfig(fast=5, slow=15))
        closes = {b.date: b.close for b in bars}
        for trade in result.trades:
            self.assertAlmostEqual(trade.entry, closes[trade.entry_date])

    def test_exit_is_never_before_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate(Path(tmp) / "sample.csv", bars=300, seed=11)
            bars = load_bars(path)
        result = run_backtest(bars, BacktestConfig(fast=5, slow=15))
        for trade in result.trades:
            self.assertGreaterEqual(trade.exit_date, trade.entry_date)


class DeterminismTests(unittest.TestCase):
    def test_same_seed_gives_same_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = generate(Path(tmp) / "a.csv", bars=400, seed=3)
            b = generate(Path(tmp) / "b.csv", bars=400, seed=3)
            result_a = run_backtest(load_bars(a), BacktestConfig(fast=5, slow=20))
            result_b = run_backtest(load_bars(b), BacktestConfig(fast=5, slow=20))

        self.assertEqual(len(result_a.trades), len(result_b.trades))
        self.assertAlmostEqual(result_a.stats.total_pnl, result_b.stats.total_pnl)
        self.assertEqual(result_a.equity, result_b.equity)

    def test_equity_curve_matches_trade_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate(Path(tmp) / "s.csv", bars=250, seed=5)
            result = run_backtest(load_bars(path), BacktestConfig(fast=3, slow=10))
        self.assertEqual(len(result.equity), len(result.trades) + 1)

    def test_too_few_bars_is_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest(bars_from([10.0] * 10), BacktestConfig(fast=5, slow=30))


class ConfigValidationTests(unittest.TestCase):
    def test_fast_must_be_shorter_than_slow(self):
        with self.assertRaises(ValueError):
            BacktestConfig(fast=30, slow=10)

    def test_stop_ticks_must_be_positive(self):
        with self.assertRaises(ValueError):
            BacktestConfig(stop_ticks=0)


class MetricsTests(unittest.TestCase):
    def test_profit_factor_and_expectancy(self):
        stats = summarize([10.0, -5.0, 20.0, -5.0], start_equity=1_000.0)
        self.assertEqual(stats.trades, 4)
        self.assertEqual(stats.wins, 2)
        self.assertAlmostEqual(stats.gross_profit, 30.0)
        self.assertAlmostEqual(stats.gross_loss, 10.0)
        self.assertAlmostEqual(stats.profit_factor, 3.0)
        self.assertAlmostEqual(stats.expectancy, 5.0)
        self.assertAlmostEqual(stats.total_pnl, 20.0)
        self.assertAlmostEqual(stats.return_pct, 2.0)

    def test_no_trades_is_safe(self):
        stats = summarize([], start_equity=1_000.0)
        self.assertEqual(stats.trades, 0)
        self.assertEqual(stats.win_rate, 0.0)
        self.assertEqual(stats.profit_factor, 0.0)

    def test_all_wins_gives_infinite_profit_factor(self):
        stats = summarize([10.0, 10.0], start_equity=1_000.0)
        self.assertEqual(stats.profit_factor, float("inf"))

    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown([100, 120, 90, 130, 80]), 50.0)
        self.assertAlmostEqual(max_drawdown([100, 110, 120]), 0.0)


class DataValidationTests(unittest.TestCase):
    def test_missing_column_names_the_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("date,open,high,close\n2024-01-01,1,2,1.5\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_bars(path)
            self.assertIn("low", str(ctx.exception))

    def test_impossible_bar_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "date,open,high,low,close\n2024-01-01,1,0.5,2,1.5\n", encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                load_bars(path)


class FrictionTests(unittest.TestCase):
    def sample(self) -> list[Bar]:
        with tempfile.TemporaryDirectory() as tmp:
            path = generate(Path(tmp) / "s.csv", bars=400, seed=7)
            return load_bars(path)

    def test_costs_are_never_free(self):
        bars = self.sample()
        free = run_backtest(
            bars, BacktestConfig(fast=5, slow=20, commission_per_side=0.0, slippage_ticks=0.0)
        )
        paid = run_backtest(bars, BacktestConfig(fast=5, slow=20))
        self.assertGreater(len(paid.trades), 0, "need trades to compare")
        self.assertLess(paid.stats.total_pnl, free.stats.total_pnl)
        self.assertEqual(free.trades[0].costs, 0.0)

    def test_cost_is_exactly_commission_plus_slippage(self):
        bars = self.sample()
        cfg = BacktestConfig(fast=5, slow=20, commission_per_side=2.5, slippage_ticks=1.0)
        for trade in run_backtest(bars, cfg).trades:
            expected = 2 * 2.5 + 2 * 1.0 * cfg.tick_value * cfg.contracts
            self.assertAlmostEqual(trade.costs, expected)

    def test_pnl_is_gross_minus_costs(self):
        bars = self.sample()
        for trade in run_backtest(bars, BacktestConfig(fast=5, slow=20)).trades:
            self.assertAlmostEqual(trade.pnl, trade.gross - trade.costs)

    def test_negative_costs_are_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(commission_per_side=-1.0)
        with self.assertRaises(ValueError):
            BacktestConfig(slippage_ticks=-1.0)


class StrategyTests(unittest.TestCase):
    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            BacktestConfig(strategy="martingale")

    def test_label_reads_like_a_human(self):
        self.assertEqual(BacktestConfig(fast=10, slow=30).label, "10/30 SMA")
        self.assertEqual(BacktestConfig(strategy="breakout", lookback=20).label, "20-bar breakout")
        self.assertIn("05-15", BacktestConfig(strategy="seasonal").label)

    def test_breakout_entry_clears_the_prior_window(self):
        prices = [10.0] * 30 + [10.0 + 0.02 * i for i in range(1, 15)]
        bars = bars_from(prices)
        cfg = BacktestConfig(strategy="breakout", lookback=20, stop_ticks=400, reward_risk=2.0)
        trades = run_backtest(bars, cfg).trades
        self.assertGreater(len(trades), 0)
        first = trades[0]
        self.assertEqual(first.side.value, "long")
        self.assertGreater(first.entry, max(b.high for b in bars[:30]))

    def test_seasonal_enters_on_the_first_day_in_the_window(self):
        bars = bars_from([10.0 + 0.01 * i for i in range(120)], start=date(2024, 4, 1))
        cfg = BacktestConfig(strategy="seasonal", stop_ticks=400, reward_risk=2.0)
        trades = run_backtest(bars, cfg).trades
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].entry_date, date(2024, 5, 15))
        self.assertLessEqual(trades[0].exit_date, date(2024, 7, 20))

    def test_seasonal_does_not_enter_mid_season(self):
        bars = bars_from([10.0 + 0.01 * i for i in range(60)], start=date(2024, 6, 1))
        cfg = BacktestConfig(strategy="seasonal", stop_ticks=400)
        self.assertEqual(run_backtest(bars, cfg).trades, [])

    def test_short_side_mirrors_long(self):
        falling = bars_from([20.0 - 0.02 * i for i in range(60)])
        cfg = BacktestConfig(strategy="breakout", lookback=10, stop_ticks=400)
        trades = run_backtest(falling, cfg).trades
        self.assertGreater(len(trades), 0)
        self.assertEqual(trades[0].side.value, "short")
        self.assertGreater(trades[0].stop, trades[0].entry)
        self.assertLess(trades[0].target, trades[0].entry)


if __name__ == "__main__":
    unittest.main()
