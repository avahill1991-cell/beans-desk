"""The risk engine.

This module is the product. Everything else is scaffolding around it.

Design rules:
  * Pure functions where possible; one small mutable object (`DayState`) for the
    things that genuinely change during a session.
  * Every rejection carries a human-readable reason, so the UI can explain itself.
  * No I/O, no network, no clock reads. Time is passed in. That makes it testable
    and makes it impossible for an LLM or a stray config edit to bypass it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class RiskPolicy:
    """Hard limits. These are the numbers the trader is not allowed to argue with."""

    account_equity: float = 2_000.0
    risk_pct: float = 1.0            # max % of equity risked per trade
    max_ticks_risk: int = 4          # widest stop allowed, in ticks
    tick_value: float = 1.25         # $ per tick per contract (MZS: 1,000 bu)
    tick_size: float = 0.00125       # price increment (1/8 cent on MZS)
    max_contracts: int = 1
    max_losses_per_day: int = 2
    max_daily_loss_pct: float = 2.0
    min_reward_risk: float = 2.0
    max_open_positions: int = 1
    session_cutoff: time = time(21, 20)   # Israel time, no new entries after this

    def __post_init__(self) -> None:
        if self.account_equity <= 0:
            raise ValueError("account_equity must be positive")
        if not 0 < self.risk_pct <= 100:
            raise ValueError("risk_pct must be in (0, 100]")
        if self.tick_size <= 0 or self.tick_value <= 0:
            raise ValueError("tick_size and tick_value must be positive")
        if self.max_ticks_risk < 1:
            raise ValueError("max_ticks_risk must be at least 1")
        if self.max_contracts < 1:
            raise ValueError("max_contracts must be at least 1")

    @property
    def max_risk_usd(self) -> float:
        return self.account_equity * self.risk_pct / 100.0

    @property
    def max_daily_loss_usd(self) -> float:
        return self.account_equity * self.max_daily_loss_pct / 100.0


@dataclass
class DayState:
    """What has happened today. Reset it at the session open, never mid-trade."""

    trades_closed: int = 0
    losses: int = 0
    realized_pnl: float = 0.0
    open_positions: int = 0

    def record_close(self, pnl: float) -> None:
        self.trades_closed += 1
        self.realized_pnl += pnl
        if pnl < 0:
            self.losses += 1

    @property
    def killed(self) -> bool:
        return self.losses >= 2 and self.realized_pnl < 0


@dataclass
class Decision:
    """The verdict on one intended trade."""

    allowed: bool
    contracts: int = 0
    risk_usd: float = 0.0
    reward_usd: float = 0.0
    reward_risk: float = 0.0
    stop_ticks: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        verdict = "ALLOW" if self.allowed else "BLOCK"
        if not self.allowed:
            return f"{verdict}: " + "; ".join(self.reasons)
        return (
            f"{verdict}: {self.contracts} contract(s), risk ${self.risk_usd:.2f}, "
            f"reward ${self.reward_usd:.2f}, R:R {self.reward_risk:.2f}, "
            f"stop {self.stop_ticks:g} ticks"
        )


def ticks_between(policy: RiskPolicy, a: float, b: float) -> float:
    """Absolute distance between two prices, expressed in ticks.

    Rounded to 6 decimals because binary floats turn an exact 4-tick stop into
    4.000000000000625, which would then fail a `> max_ticks` comparison.
    """
    return round(abs(a - b) / policy.tick_size, 6)


def evaluate(
    policy: RiskPolicy,
    day: DayState,
    side: Side | str,
    entry: float,
    stop: float | None,
    target: float | None,
    now: time | None = None,
) -> Decision:
    """Decide whether this trade may be taken, and at what size.

    This function never places anything. It only says yes or no, and why.
    """
    reasons: list[str] = []
    side = Side(side) if not isinstance(side, Side) else side

    # --- rule 1: a stop is mandatory -------------------------------------
    if stop is None:
        return Decision(False, reasons=["no stop-loss set - entry refused"])

    if entry <= 0 or stop <= 0:
        return Decision(False, reasons=["entry and stop must be positive prices"])

    # --- direction sanity -------------------------------------------------
    if side is Side.LONG and stop >= entry:
        return Decision(False, reasons=["long stop must be below entry"])
    if side is Side.SHORT and stop <= entry:
        return Decision(False, reasons=["short stop must be above entry"])

    # --- rule 2: stop width ----------------------------------------------
    stop_ticks = ticks_between(policy, entry, stop)
    if stop_ticks < 1:
        return Decision(False, reasons=["stop is inside one tick - not a real stop"])
    if stop_ticks > policy.max_ticks_risk:
        reasons.append(
            f"stop is {stop_ticks:g} ticks wide, max is {policy.max_ticks_risk}"
        )

    risk_per_contract = stop_ticks * policy.tick_value

    # --- rule 3: position size from risk budget ---------------------------
    size_by_risk = int(policy.max_risk_usd // risk_per_contract) if risk_per_contract else 0
    contracts = min(size_by_risk, policy.max_contracts)
    if contracts < 1:
        reasons.append(
            f"one contract risks ${risk_per_contract:.2f}, budget is ${policy.max_risk_usd:.2f}"
        )

    # --- rule 4: reward:risk ---------------------------------------------
    reward_risk = 0.0
    reward_usd = 0.0
    if target is None:
        reasons.append("no take-profit set")
    else:
        if side is Side.LONG and target <= entry:
            reasons.append("long target must be above entry")
        elif side is Side.SHORT and target >= entry:
            reasons.append("short target must be below entry")
        else:
            reward_ticks = ticks_between(policy, entry, target)
            reward_risk = round(reward_ticks / stop_ticks, 6) if stop_ticks else 0.0
            reward_usd = reward_ticks * policy.tick_value * max(contracts, 1)
            if reward_risk < policy.min_reward_risk:
                reasons.append(
                    f"reward:risk is {reward_risk:.2f}, minimum is {policy.min_reward_risk:.2f}"
                )

    # --- rules 5 and 6: the day's ledger ----------------------------------
    if day.losses >= policy.max_losses_per_day:
        reasons.append(
            f"{day.losses} losses today, limit is {policy.max_losses_per_day} - done for the day"
        )
    if day.realized_pnl <= -policy.max_daily_loss_usd:
        reasons.append(
            f"daily loss ${abs(day.realized_pnl):.2f} reached the "
            f"${policy.max_daily_loss_usd:.2f} kill-switch limit"
        )

    # --- rule 7: session cutoff -------------------------------------------
    if now is not None and now >= policy.session_cutoff:
        reasons.append(
            f"{now.strftime('%H:%M')} is past the {policy.session_cutoff.strftime('%H:%M')} cutoff"
        )

    # --- rule 8: one position at a time -----------------------------------
    if day.open_positions >= policy.max_open_positions:
        reasons.append(
            f"{day.open_positions} position(s) already open, max is {policy.max_open_positions}"
        )

    allowed = not reasons
    return Decision(
        allowed=allowed,
        contracts=contracts if allowed else 0,
        risk_usd=risk_per_contract * contracts if allowed else 0.0,
        reward_usd=reward_usd if allowed else 0.0,
        reward_risk=reward_risk,
        stop_ticks=stop_ticks,
        reasons=reasons,
    )
