"""The rules engine, one rule at a time.

If a rule here ever stops failing when it should, the product has lost the only
thing it sells.
"""

from __future__ import annotations

import unittest
from datetime import time

from beansdesk.risk import DayState, RiskPolicy, Side, evaluate, ticks_between


def policy(**overrides) -> RiskPolicy:
    base = dict(
        account_equity=2_000.0,
        risk_pct=1.0,
        max_ticks_risk=4,
        tick_value=1.25,
        tick_size=0.00125,
        max_contracts=1,
        max_losses_per_day=2,
        max_daily_loss_pct=2.0,
        min_reward_risk=2.0,
        max_open_positions=1,
        session_cutoff=time(21, 20),
    )
    base.update(overrides)
    return RiskPolicy(**base)


class NoStopTests(unittest.TestCase):
    def test_trade_without_stop_is_refused(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, None, 12.42)
        self.assertFalse(d.allowed)
        self.assertIn("no stop-loss", d.reasons[0])

    def test_zero_stop_is_refused(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 0.0, 12.42)
        self.assertFalse(d.allowed)


class StopWidthTests(unittest.TestCase):
    def test_stop_wider_than_limit_is_blocked(self):
        # 0.00625 = 5 ticks, limit is 4
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.39375, 12.4150)
        self.assertFalse(d.allowed)
        self.assertTrue(any("5 ticks wide" in r for r in d.reasons))

    def test_stop_inside_one_tick_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3995, 12.4100)
        self.assertFalse(d.allowed)
        self.assertTrue(any("inside one tick" in r for r in d.reasons))

    def test_exactly_four_ticks_is_allowed(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertTrue(d.allowed, d.reasons)
        self.assertEqual(d.stop_ticks, 4.0)


class DirectionTests(unittest.TestCase):
    def test_long_stop_above_entry_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.4050, 12.4100)
        self.assertFalse(d.allowed)
        self.assertTrue(any("below entry" in r for r in d.reasons))

    def test_short_stop_below_entry_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.SHORT, 12.40, 12.3950, 12.3900)
        self.assertFalse(d.allowed)
        self.assertTrue(any("above entry" in r for r in d.reasons))

    def test_valid_short_is_allowed(self):
        d = evaluate(policy(), DayState(), Side.SHORT, 12.40, 12.4050, 12.3900)
        self.assertTrue(d.allowed, d.reasons)


class RewardRiskTests(unittest.TestCase):
    def test_one_to_one_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4050)
        self.assertFalse(d.allowed)
        self.assertTrue(any("reward:risk" in r for r in d.reasons))

    def test_two_to_one_is_allowed(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertTrue(d.allowed, d.reasons)
        self.assertAlmostEqual(d.reward_risk, 2.0)

    def test_missing_target_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, None)
        self.assertFalse(d.allowed)
        self.assertTrue(any("take-profit" in r for r in d.reasons))


class SizingTests(unittest.TestCase):
    def test_one_contract_risks_five_dollars(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertEqual(d.contracts, 1)
        self.assertAlmostEqual(d.risk_usd, 5.0)
        self.assertAlmostEqual(d.reward_usd, 10.0)

    def test_size_is_capped_by_max_contracts(self):
        d = evaluate(
            policy(max_contracts=5), DayState(), Side.LONG, 12.40, 12.3950, 12.4100
        )
        self.assertTrue(d.allowed, d.reasons)
        self.assertEqual(d.contracts, 4)          # $20 budget / $5 per contract
        self.assertAlmostEqual(d.risk_usd, 20.0)

    def test_account_too_small_is_blocked(self):
        d = evaluate(
            policy(account_equity=100.0), DayState(), Side.LONG, 12.40, 12.3950, 12.4100
        )
        self.assertFalse(d.allowed)
        self.assertTrue(any("budget is" in r for r in d.reasons))


class DayLimitTests(unittest.TestCase):
    def test_third_trade_after_two_losses_is_blocked(self):
        day = DayState()
        day.record_close(-5.0)
        day.record_close(-5.0)
        d = evaluate(policy(), day, Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertFalse(d.allowed)
        self.assertTrue(any("losses today" in r for r in d.reasons))

    def test_wins_do_not_count_as_losses(self):
        day = DayState()
        day.record_close(10.0)
        day.record_close(-5.0)
        d = evaluate(policy(), day, Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertTrue(d.allowed, d.reasons)

    def test_daily_loss_limit_triggers_kill_switch(self):
        day = DayState(realized_pnl=-40.0)        # 2% of 2000
        d = evaluate(policy(), day, Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertFalse(d.allowed)
        self.assertTrue(any("kill-switch" in r for r in d.reasons))


class SessionTests(unittest.TestCase):
    def test_entry_after_cutoff_is_blocked(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4100, now=time(21, 30))
        self.assertFalse(d.allowed)
        self.assertTrue(any("cutoff" in r for r in d.reasons))

    def test_entry_before_cutoff_is_allowed(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, 12.3950, 12.4100, now=time(19, 0))
        self.assertTrue(d.allowed, d.reasons)

    def test_second_position_is_blocked(self):
        day = DayState(open_positions=1)
        d = evaluate(policy(), day, Side.LONG, 12.40, 12.3950, 12.4100)
        self.assertFalse(d.allowed)
        self.assertTrue(any("already open" in r for r in d.reasons))


class PolicyValidationTests(unittest.TestCase):
    def test_negative_equity_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskPolicy(account_equity=-1)

    def test_risk_percent_out_of_range_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskPolicy(risk_pct=0)

    def test_zero_tick_size_is_rejected(self):
        with self.assertRaises(ValueError):
            RiskPolicy(tick_size=0)

    def test_budget_helpers(self):
        p = policy()
        self.assertAlmostEqual(p.max_risk_usd, 20.0)
        self.assertAlmostEqual(p.max_daily_loss_usd, 40.0)


class HelperTests(unittest.TestCase):
    def test_ticks_between(self):
        self.assertAlmostEqual(ticks_between(policy(), 12.40, 12.3950), 4.0)
        self.assertAlmostEqual(ticks_between(policy(), 12.3950, 12.40), 4.0)

    def test_blocked_decision_has_no_size(self):
        d = evaluate(policy(), DayState(), Side.LONG, 12.40, None, None)
        self.assertEqual(d.contracts, 0)
        self.assertEqual(d.risk_usd, 0.0)
        self.assertTrue(d.summary.startswith("BLOCK"))


if __name__ == "__main__":
    unittest.main()
