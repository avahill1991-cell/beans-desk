"""Command line entry point.

The CLI is the same engine the Windows shell will call. Keeping it first means the
UI is a thin layer over something that already works, instead of the other way round.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path

from beansdesk import __version__
from beansdesk.backtest import BacktestConfig, run_backtest
from beansdesk.data import load_bars
from beansdesk.journal import analyse, append_trade
from beansdesk.report import write_report
from beansdesk.risk import DayState, RiskPolicy, evaluate


def _hhmm(raw: str) -> time:
    try:
        h, m = raw.split(":")
        return time(int(h), int(m))
    except Exception as exc:  # noqa: BLE001 - argparse wants a clean message
        raise argparse.ArgumentTypeError(f"expected HH:MM, got {raw!r}") from exc


def _cmd_demo(args: argparse.Namespace) -> int:
    from beansdesk.sample import generate

    out = generate(args.out, bars=args.bars, seed=args.seed)
    print(f"wrote {out} ({args.bars} bars)")
    print(f"next:  python -m beansdesk backtest --data {out} --out examples/report.html")
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    bars = load_bars(args.data)
    cfg = BacktestConfig(
        strategy=args.strategy,
        fast=args.fast,
        slow=args.slow,
        lookback=args.lookback,
        entry_month=args.entry_month,
        entry_day=args.entry_day,
        exit_month=args.exit_month,
        exit_day=args.exit_day,
        stop_ticks=args.stop_ticks,
        reward_risk=args.rr,
        tick_size=args.tick_size,
        tick_value=args.tick_value,
        contracts=args.contracts,
        start_equity=args.equity,
        commission_per_side=args.commission,
        slippage_ticks=args.slippage,
    )
    result = run_backtest(bars, cfg)
    s = result.stats

    print(f"\n  {len(bars)} bars  {bars[0].date} to {bars[-1].date}")
    print(f"  {cfg.label}  {cfg.stop_ticks}-tick stop  {cfg.reward_risk:g}R  "
          f"${cfg.commission_per_side:.2f}/side  {cfg.slippage_ticks:g} tick slip")
    print(f"  {'-' * 46}")
    for label, value in s.as_rows():
        print(f"  {label:<20}{value:>24}")
    print(f"  {'-' * 46}")

    if result.trades:
        best = max(result.trades, key=lambda t: t.pnl)
        worst = min(result.trades, key=lambda t: t.pnl)
        print(f"  best trade   {best.entry_date}  {best.pnl:+.2f}")
        print(f"  worst trade  {worst.entry_date}  {worst.pnl:+.2f}")

    if args.out:
        path = write_report(result, args.out, title=args.title)
        print(f"\n  report -> {path}")

    if s.trades and s.profit_factor < 1.0:
        print("\n  note: profit factor below 1.0. This strategy lost money on this data.")
    return 0


def _cmd_risk_check(args: argparse.Namespace) -> int:
    policy = RiskPolicy(
        account_equity=args.equity,
        risk_pct=args.risk_pct,
        max_ticks_risk=args.max_ticks,
        tick_value=args.tick_value,
        tick_size=args.tick_size,
        max_contracts=args.contracts,
        session_cutoff=_hhmm(args.cutoff),
    )
    day = DayState(
        losses=args.losses,
        realized_pnl=args.realized,
        open_positions=args.open,
    )
    decision = evaluate(
        policy=policy,
        day=day,
        side=args.side,
        entry=args.entry,
        stop=args.stop,
        target=args.target,
        now=_hhmm(args.now) if args.now else None,
    )

    print(f"\n  {decision.summary}\n")
    if not decision.allowed:
        for reason in decision.reasons:
            print(f"    - {reason}")
        print()
        return 2
    return 0


def _cmd_journal(args: argparse.Namespace) -> int:
    if args.add_side:
        if args.add_entry is None or args.add_exit is None:
            print("--add-side needs --add-entry and --add-exit", file=sys.stderr)
            return 2
        when = datetime.strptime(args.when, "%Y-%m-%dT%H:%M") if args.when else datetime.now()
        row = append_trade(
            args.csv,
            when=when,
            contract=args.contract,
            side=args.add_side,
            entry=args.add_entry,
            exit=args.add_exit,
            contracts=args.contracts,
            tick_size=args.tick_size,
            tick_value=args.tick_value,
            setup=args.setup,
            reason=args.reason,
            sentiment=args.sentiment,
            followed_plan=not args.broke_plan,
            notes=args.notes,
        )
        print(f"logged: {row['Date']} {row['Time_IL']} {row['Side']} "
              f"{row['Ticks']} ticks  {row['PnL_USD']} USD")

    report = analyse(args.csv, start_equity=args.equity)
    if report.rows == 0:
        print(f"\n  journal is empty: {args.csv}")
        return 0

    print(f"\n  {report.rows} trades in {args.csv}")
    print(f"  {'-' * 46}")
    for label, value in report.stats.as_rows():
        print(f"  {label:<20}{value:>24}")
    print(f"  {'plan followed':<20}{report.followed_plan_pct:>23.1f}%")
    print(f"  {'avg sentiment':<20}{report.avg_sentiment:>24.1f}")
    print(f"  {'-' * 46}")
    if report.by_setup:
        print("  by setup:")
        for name, pnl in report.by_setup.items():
            print(f"    {name:<24}{pnl:>+10.2f}")
    if report.followed_plan_pct < 70:
        print("\n  warning: under 70% plan adherence. The leaks are behavioural, not analytical.")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    from beansdesk.sources import fetch_yahoo, write_csv

    result = fetch_yahoo(args.symbol, args.range, args.interval, refresh=args.refresh)
    bars = result.bars
    out = write_csv(bars, args.out)
    tag = "cache" if result.from_cache else "download"
    print(f"\n  {result.symbol}  {len(bars)} bars  {bars[0].date} to {bars[-1].date}")
    print(f"  source: {result.source} ({tag})  {result.note}")
    print(f"  first close {bars[0].close:.4f}   last close {bars[-1].close:.4f}")
    print(f"  written -> {out}")
    print(f"\n  next:  python -m beansdesk backtest --data {out} --out examples/report.html")
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    bars = load_bars(args.data)
    stops = [int(s) for s in args.stops.split(",") if s.strip()]
    if not stops:
        print("--stops needs at least one number", file=sys.stderr)
        return 2

    print(f"\n  {args.data}  {len(bars)} bars  {bars[0].date} to {bars[-1].date}")
    base = BacktestConfig(
        strategy=args.strategy,
        fast=args.fast,
        slow=args.slow,
        lookback=args.lookback,
        entry_month=args.entry_month,
        entry_day=args.entry_day,
        exit_month=args.exit_month,
        exit_day=args.exit_day,
        reward_risk=args.rr,
        start_equity=args.equity,
        contracts=args.contracts,
        commission_per_side=args.commission,
        slippage_ticks=args.slippage,
    )
    print(f"  {base.label}   {args.rr:g}R target   equity ${args.equity:,.0f}")
    print(f"  {'-' * 66}")
    print(f"  {'stop':>6}{'trades':>8}{'win%':>8}{'pf':>8}{'net $':>11}{'max dd $':>11}")
    print(f"  {'-' * 66}")

    best = None
    for ticks in stops:
        cfg = replace(base, stop_ticks=ticks)
        s = run_backtest(bars, cfg).stats
        pf = "inf" if s.profit_factor == float("inf") else f"{s.profit_factor:.2f}"
        print(
            f"  {ticks:>6}{s.trades:>8}{s.win_rate:>7.1f}%{pf:>8}"
            f"{s.total_pnl:>11.2f}{s.max_drawdown:>11.2f}"
        )
        if s.trades >= 5 and (best is None or s.profit_factor > best[1]):
            best = (ticks, s.profit_factor)

    print(f"  {'-' * 66}")
    if best:
        print(f"  widest profit factor: {best[1]:.2f} at {best[0]} ticks")
    print("\n  a stop width is not a strategy. this only shows which one survived this data.")
    return 0


def _cmd_license(args: argparse.Namespace) -> int:
    from beansdesk import licensing

    if args.issue:
        print(licensing.make_key(args.issue, plan=args.plan, days=args.days))
        return 0

    if args.activate:
        info = licensing.verify_key(args.activate)
        if not info.valid:
            print(f"invalid key: {info.reason}", file=sys.stderr)
            return 2
        path = licensing.save_key(args.activate)
        print(f"\n  activated {info.plan.upper()} for {info.email}")
        print(f"  expires {info.expires} ({info.days_left} days left)")
        print(f"  saved -> {path}")
        return 0

    info = licensing.status()
    if info.valid:
        print(f"\n  {info.plan.upper()}  {info.email}  expires {info.expires}  "
              f"({info.days_left} days left)")
    else:
        print(f"\n  TRIAL  ({info.reason})")
        print("  activate:  beansdesk license --activate <KEY>")
        print("  issue:     beansdesk license --issue you@example.com --days 365")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    from beansdesk.updater import check

    info = check(__version__, args.manifest)
    if info.error:
        print(f"\n  could not check for updates: {info.error}")
        print("  pass --manifest with a url or a local json file")
        return 0
    if info.available:
        print(f"\n  {info.latest} is available (you have {info.current})")
        if info.notes:
            print(f"  {info.notes}")
        if info.url:
            print(f"  {info.url}")
    else:
        print(f"\n  up to date ({info.current})")
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    try:
        from beansdesk.gui import main as gui_main
    except ImportError:
        print(
            "the desktop shell needs customtkinter:\n"
            "  python -m pip install customtkinter",
            file=sys.stderr,
        )
        return 1
    return gui_main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="beansdesk",
        description="Beans Desk - risk-first backtesting, sizing and journalling.",
    )
    p.add_argument("--version", action="version", version=f"beansdesk {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="write a synthetic OHLC csv")
    demo.add_argument("--out", default="examples/sample_mzs.csv")
    demo.add_argument("--bars", type=int, default=520)
    demo.add_argument("--seed", type=int, default=7)
    demo.set_defaults(func=_cmd_demo)

    bt = sub.add_parser("backtest", help="run the SMA-cross backtest")
    bt.add_argument("--data", required=True, help="OHLC csv")
    bt.add_argument("--out", help="write an HTML tearsheet here")
    bt.add_argument("--title", default="Backtest report")
    bt.add_argument("--fast", type=int, default=10)
    bt.add_argument("--slow", type=int, default=30)
    bt.add_argument("--strategy", choices=["sma", "breakout", "seasonal"], default="sma")
    bt.add_argument("--lookback", type=int, default=20, help="breakout window in bars")
    bt.add_argument("--entry-month", type=int, default=5)
    bt.add_argument("--entry-day", type=int, default=15)
    bt.add_argument("--exit-month", type=int, default=7)
    bt.add_argument("--exit-day", type=int, default=20)
    bt.add_argument("--stop-ticks", type=int, default=4)
    bt.add_argument("--rr", type=float, default=2.0)
    bt.add_argument("--tick-size", type=float, default=0.00125)
    bt.add_argument("--tick-value", type=float, default=1.25)
    bt.add_argument("--contracts", type=int, default=1)
    bt.add_argument("--equity", type=float, default=2_000.0)
    bt.add_argument("--commission", type=float, default=1.0, help="$ per contract per side")
    bt.add_argument("--slippage", type=float, default=0.5, help="ticks lost on each fill")
    bt.set_defaults(func=_cmd_backtest)

    rc = sub.add_parser("risk-check", help="approve or block one intended trade")
    rc.add_argument("--equity", type=float, required=True)
    rc.add_argument("--entry", type=float, required=True)
    rc.add_argument("--stop", type=float, required=True)
    rc.add_argument("--target", type=float, required=True)
    rc.add_argument("--side", choices=["long", "short"], default="long")
    rc.add_argument("--risk-pct", type=float, default=1.0)
    rc.add_argument("--max-ticks", type=int, default=4)
    rc.add_argument("--tick-size", type=float, default=0.00125)
    rc.add_argument("--tick-value", type=float, default=1.25)
    rc.add_argument("--contracts", type=int, default=1)
    rc.add_argument("--losses", type=int, default=0, help="losses already taken today")
    rc.add_argument("--realized", type=float, default=0.0, help="realised P&L today")
    rc.add_argument("--open", type=int, default=0, help="positions currently open")
    rc.add_argument("--now", help="current time HH:MM, checked against the cutoff")
    rc.add_argument("--cutoff", default="21:20", help="no new entries after this HH:MM")
    rc.set_defaults(func=_cmd_risk_check)

    jr = sub.add_parser("journal", help="log a trade and report on the journal")
    jr.add_argument("--csv", default="journal.csv")
    jr.add_argument("--equity", type=float, default=2_000.0)
    jr.add_argument("--add-side", choices=["long", "short", "buy", "sell"])
    jr.add_argument("--add-entry", type=float)
    jr.add_argument("--add-exit", type=float)
    jr.add_argument("--when", help="ISO datetime, e.g. 2026-11-20T17:45")
    jr.add_argument("--contract", default="MZS")
    jr.add_argument("--contracts", type=int, default=1)
    jr.add_argument("--tick-size", type=float, default=0.00125)
    jr.add_argument("--tick-value", type=float, default=1.25)
    jr.add_argument("--setup", default="")
    jr.add_argument("--reason", default="")
    jr.add_argument("--sentiment", type=int, default=3)
    jr.add_argument("--broke-plan", action="store_true", help="mark the plan as not followed")
    jr.add_argument("--notes", default="")
    jr.set_defaults(func=_cmd_journal)

    fe = sub.add_parser("fetch", help="download daily bars from Yahoo and cache them")
    fe.add_argument("--symbol", default="ZS=F", help="Yahoo symbol, e.g. ZS=F (soybean)")
    fe.add_argument("--range", default="10y", help="1mo, 6mo, 1y, 2y, 5y, 10y, max")
    fe.add_argument("--interval", default="1d")
    fe.add_argument("--out", default="data/ZS_F.csv")
    fe.add_argument("--refresh", action="store_true", help="ignore the local cache")
    fe.set_defaults(func=_cmd_fetch)

    sw = sub.add_parser("sweep", help="compare stop widths on the same data")
    sw.add_argument("--data", required=True)
    sw.add_argument("--stops", default="4,8,12,20,40,80")
    sw.add_argument("--fast", type=int, default=10)
    sw.add_argument("--slow", type=int, default=30)
    sw.add_argument("--strategy", choices=["sma", "breakout", "seasonal"], default="sma")
    sw.add_argument("--lookback", type=int, default=20)
    sw.add_argument("--entry-month", type=int, default=5)
    sw.add_argument("--entry-day", type=int, default=15)
    sw.add_argument("--exit-month", type=int, default=7)
    sw.add_argument("--exit-day", type=int, default=20)
    sw.add_argument("--rr", type=float, default=2.0)
    sw.add_argument("--contracts", type=int, default=1)
    sw.add_argument("--equity", type=float, default=2_000.0)
    sw.add_argument("--commission", type=float, default=1.0)
    sw.add_argument("--slippage", type=float, default=0.5)
    sw.set_defaults(func=_cmd_sweep)

    lc = sub.add_parser("license", help="show, activate or issue a licence key")
    lc.add_argument("--activate", help="key bought from the store")
    lc.add_argument("--issue", metavar="EMAIL", help="seller only: print a new key")
    lc.add_argument("--plan", default="pro")
    lc.add_argument("--days", type=int, default=365)
    lc.set_defaults(func=_cmd_license)

    up = sub.add_parser("update", help="check a version manifest for a newer build")
    up.add_argument("--manifest", default=None)
    up.set_defaults(func=_cmd_update)

    gp = sub.add_parser("gui", help="open the desktop shell")
    gp.set_defaults(func=_cmd_gui)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
