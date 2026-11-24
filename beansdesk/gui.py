"""The Windows shell.

Layout and colour come from `customtkinter` (MIT) - see THIRD_PARTY_NOTICES.md.
Everything else here is ours. The rule for this file: it must never do maths.
It collects inputs, calls the engine, and renders the answer. If a rule ever
appears in this file, the risk engine has stopped being the single source of truth.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

import customtkinter as ctk

from beansdesk import __version__
from beansdesk.backtest import BacktestConfig, BacktestResult, run_backtest
from beansdesk.data import load_bars
from beansdesk.journal import analyse, read_journal
from beansdesk.report import write_report
from beansdesk.risk import DayState, RiskPolicy, Side, evaluate

BG = "#0f1115"
CARD = "#171a21"
LINE = "#252a35"
TEXT = "#e6e8ee"
MUTED = "#8b93a7"
UP = "#35d07f"
DOWN = "#ff5d5d"
ACCENT = "#6ea8fe"

UI = ("Segoe UI", 13)
UI_SMALL = ("Segoe UI", 11)
UI_BOLD = ("Segoe UI", 13, "bold")
NUM = ("Consolas", 20)
NUM_SMALL = ("Consolas", 12)


def money(value: float) -> str:
    return f"${value:,.2f}"


def card(master, **kwargs) -> ctk.CTkFrame:
    options = dict(fg_color=CARD, corner_radius=12, border_width=1, border_color=LINE)
    options.update(kwargs)
    return ctk.CTkFrame(master, **options)


def field(master, label: str, default: str, width: int = 130) -> ctk.CTkEntry:
    ctk.CTkLabel(master, text=label, font=UI_SMALL, text_color=MUTED, anchor="w").pack(
        fill="x", pady=(0, 3)
    )
    entry = ctk.CTkEntry(
        master, width=width, height=34, font=NUM_SMALL,
        fg_color=BG, border_color=LINE, text_color=TEXT,
    )
    entry.insert(0, default)
    entry.pack(fill="x")
    return entry


def stat_card(master, label: str, value: str = "-") -> ctk.CTkLabel:
    box = card(master, corner_radius=10)
    box.pack(side="left", fill="both", expand=True, padx=(0, 8))
    ctk.CTkLabel(box, text=label.upper(), font=("Segoe UI", 10), text_color=MUTED).pack(
        anchor="w", padx=14, pady=(10, 0)
    )
    value_label = ctk.CTkLabel(box, text=value, font=NUM, text_color=TEXT)
    value_label.pack(anchor="w", padx=14, pady=(0, 10))
    return value_label


def draw_equity(canvas: tk.Canvas, values: list[float], start: float) -> None:
    canvas.delete("all")
    width = max(canvas.winfo_width(), 60)
    height = max(canvas.winfo_height(), 60)
    if len(values) < 2:
        canvas.create_text(width / 2, height / 2, text="run a backtest", fill=MUTED,
                           font=("Segoe UI", 12))
        return

    pad = 14
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(values) - 1)

    def y(value: float) -> float:
        return height - pad - (value - lo) / span * (height - 2 * pad)

    points: list[float] = []
    for i, value in enumerate(values):
        points.extend((pad + i * step, y(value)))

    base = y(start)
    canvas.create_line(pad, base, width - pad, base, fill="#3a4152", dash=(4, 4))

    colour = UP if values[-1] >= start else DOWN
    canvas.create_polygon(
        [pad, height - pad, *points, pad + (len(values) - 1) * step, height - pad],
        fill=colour, outline="", stipple="gray25",
    )
    canvas.create_line(*points, fill=colour, width=2, smooth=False)


class BacktestPage(ctk.CTkFrame):
    def __init__(self, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.result: BacktestResult | None = None

        ctk.CTkLabel(self, text="Backtest", font=("Segoe UI", 22, "bold"), text_color=TEXT).pack(
            anchor="w", pady=(0, 2)
        )
        ctk.CTkLabel(
            self,
            text="Load an OHLC csv, run the deterministic SMA-cross engine, export a tearsheet.",
            font=UI_SMALL, text_color=MUTED,
        ).pack(anchor="w", pady=(0, 14))

        controls = card(self)
        controls.pack(fill="x", pady=(0, 14))

        top = ctk.CTkFrame(controls, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(top, text="DATA FILE", font=("Segoe UI", 10), text_color=MUTED).pack(
            anchor="w", pady=(0, 3)
        )
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x")
        self.data_path = ctk.CTkEntry(
            row, height=34, font=NUM_SMALL, fg_color=BG, border_color=LINE, text_color=TEXT
        )
        self.data_path.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row, text="Browse", width=90, height=34, command=self._browse,
            fg_color="#2a3040", hover_color="#343c50", text_color=TEXT,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            row, text="Get ZS=F", width=100, height=34, command=self._fetch,
            fg_color="#2a3040", hover_color="#343c50", text_color=ACCENT,
        ).pack(side="left", padx=(8, 0))

        grid = ctk.CTkFrame(controls, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 14))
        specs = [
            ("FAST SMA", "10"), ("SLOW SMA", "30"), ("STOP (TICKS)", "4"),
            ("REWARD:RISK", "2.0"), ("EQUITY $", "2000"), ("CONTRACTS", "1"),
        ]
        for i, (label, default) in enumerate(specs):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 8))
            grid.columnconfigure(i, weight=1)
            setattr(self, f"f_{i}", field(cell, label, default))

        actions = ctk.CTkFrame(controls, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            actions, text="Run backtest", height=38, width=160, command=self._run,
            fg_color=ACCENT, hover_color="#5b93e6", text_color="#0b1020", font=UI_BOLD,
        ).pack(side="left")
        self.export_btn = ctk.CTkButton(
            actions, text="Export report", height=38, width=140, command=self._export,
            fg_color="#2a3040", hover_color="#343c50", text_color=TEXT, state="disabled",
        )
        self.export_btn.pack(side="left", padx=(8, 0))
        self.status = ctk.CTkLabel(actions, text="", font=UI_SMALL, text_color=MUTED)
        self.status.pack(side="left", padx=(14, 0))

        stats_row = ctk.CTkFrame(self, fg_color="transparent", height=78)
        stats_row.pack(fill="x", pady=(0, 14))
        self.s_trades = stat_card(stats_row, "trades")
        self.s_win = stat_card(stats_row, "win rate")
        self.s_pf = stat_card(stats_row, "profit factor")
        self.s_pnl = stat_card(stats_row, "net p&l")
        self.s_dd = stat_card(stats_row, "max drawdown")

        chart = card(self)
        chart.pack(fill="both", expand=True)
        ctk.CTkLabel(chart, text="EQUITY CURVE", font=("Segoe UI", 10), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(12, 0)
        )
        self.canvas = tk.Canvas(chart, bg=CARD, highlightthickness=0, height=240)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an OHLC csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if path:
            self.data_path.delete(0, "end")
            self.data_path.insert(0, path)

    def _fetch(self) -> None:
        from beansdesk.sources import fetch_yahoo, write_csv

        self.status.configure(text="downloading ZS=F, 10 years...", text_color=MUTED)
        self.update_idletasks()
        try:
            result = fetch_yahoo("ZS=F", "10y")
            out = write_csv(result.bars, Path("data") / "ZS_F.csv")
        except Exception as exc:  # noqa: BLE001 - any network failure lands here
            self.status.configure(text=str(exc)[:110], text_color=DOWN)
            return

        self.data_path.delete(0, "end")
        self.data_path.insert(0, str(out))
        first, last = result.bars[0].date, result.bars[-1].date
        self.status.configure(
            text=f"{len(result.bars)} bars, {first} to {last}"
                 + ("  (cached)" if result.from_cache else ""),
            text_color=UP,
        )

    def _value(self, index: int, cast, fallback):
        try:
            return cast(getattr(self, f"f_{index}").get())
        except (TypeError, ValueError):
            return fallback

    def _run(self) -> None:
        path = self.data_path.get().strip()
        if not path:
            self.status.configure(text="Choose a csv first.", text_color=DOWN)
            return
        try:
            bars = load_bars(path)
            cfg = BacktestConfig(
                fast=self._value(0, int, 10),
                slow=self._value(1, int, 30),
                stop_ticks=self._value(2, int, 4),
                reward_risk=self._value(3, float, 2.0),
                start_equity=self._value(4, float, 2000.0),
                contracts=self._value(5, int, 1),
            )
            self.result = run_backtest(bars, cfg)
        except (OSError, ValueError) as exc:
            self.status.configure(text=str(exc), text_color=DOWN)
            return

        s = self.result.stats
        self.s_trades.configure(text=str(s.trades))
        self.s_win.configure(text=f"{s.win_rate:.1f}%",
                             text_color=UP if s.win_rate >= 50 else TEXT)
        self.s_pf.configure(text=("inf" if s.profit_factor == float("inf")
                                  else f"{s.profit_factor:.2f}"),
                            text_color=UP if s.profit_factor >= 1 else DOWN)
        self.s_pnl.configure(text=money(s.total_pnl), text_color=UP if s.total_pnl >= 0 else DOWN)
        self.s_dd.configure(text=money(s.max_drawdown), text_color=TEXT)
        self.status.configure(
            text=f"{len(bars)} bars, {s.trades} trades, {s.expectancy:+.2f}/trade",
            text_color=MUTED,
        )
        self.export_btn.configure(state="normal")
        self._redraw()

    def _redraw(self) -> None:
        if not self.result:
            draw_equity(self.canvas, [], 0.0)
            return
        draw_equity(self.canvas, self.result.equity, self.result.config.start_equity)

    def _export(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".html", filetypes=[("HTML report", "*.html")],
            initialfile="backtest-report.html",
        )
        if not path:
            return
        write_report(self.result, path)
        self.status.configure(text=f"report saved to {Path(path).name}", text_color=UP)


class RiskPage(ctk.CTkFrame):
    def __init__(self, master) -> None:
        super().__init__(master, fg_color="transparent")

        ctk.CTkLabel(self, text="Risk gate", font=("Segoe UI", 22, "bold"), text_color=TEXT).pack(
            anchor="w", pady=(0, 2)
        )
        ctk.CTkLabel(
            self,
            text="Every intended trade goes through the rules engine. No stop, no entry.",
            font=UI_SMALL, text_color=MUTED,
        ).pack(anchor="w", pady=(0, 14))

        self.banner = card(self, fg_color="#1a1d26", border_color=LINE)
        self.banner.pack(fill="x", pady=(0, 14))
        self.verdict = ctk.CTkLabel(self.banner, text="NOT CHECKED", font=("Segoe UI", 26, "bold"),
                                    text_color=MUTED)
        self.verdict.pack(anchor="w", padx=18, pady=(16, 2))
        self.verdict_detail = ctk.CTkLabel(self.banner, text="Fill the ticket and press Check trade.",
                                           font=NUM_SMALL, text_color=MUTED, justify="left")
        self.verdict_detail.pack(anchor="w", padx=18, pady=(0, 16))

        form = card(self)
        form.pack(fill="x", pady=(0, 14))
        grid = ctk.CTkFrame(form, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=14)

        specs = [
            ("ACCOUNT EQUITY", "2000"), ("ENTRY", "12.4000"), ("STOP", "12.3950"),
            ("TARGET", "12.4100"), ("LOSSES TODAY", "0"), ("OPEN POSITIONS", "0"),
        ]
        self.inputs: dict[str, ctk.CTkEntry] = {}
        for i, (label, default) in enumerate(specs):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 8))
            grid.columnconfigure(i, weight=1)
            self.inputs[label] = field(cell, label, default)

        side_row = ctk.CTkFrame(form, fg_color="transparent")
        side_row.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkLabel(side_row, text="SIDE", font=UI_SMALL, text_color=MUTED).pack(side="left")
        self.side = ctk.CTkOptionMenu(
            side_row, values=["long", "short"], width=110, height=32,
            fg_color=BG, button_color="#2a3040", button_hover_color="#343c50",
            text_color=TEXT, dropdown_fg_color=CARD,
        )
        self.side.pack(side="left", padx=(10, 24))
        ctk.CTkLabel(side_row, text="REALISED P&L TODAY", font=UI_SMALL, text_color=MUTED).pack(
            side="left"
        )
        self.realized = ctk.CTkEntry(side_row, width=110, height=32, font=NUM_SMALL,
                                     fg_color=BG, border_color=LINE, text_color=TEXT)
        self.realized.insert(0, "0")
        self.realized.pack(side="left", padx=(10, 24))
        ctk.CTkButton(
            side_row, text="Check trade", width=150, height=36, command=self._check,
            fg_color=ACCENT, hover_color="#5b93e6", text_color="#0b1020", font=UI_BOLD,
        ).pack(side="left")

        self.reasons = ctk.CTkTextbox(self, fg_color=CARD, text_color=TEXT, font=NUM_SMALL,
                                      border_width=1, border_color=LINE, corner_radius=12,
                                      wrap="word")
        self.reasons.pack(fill="both", expand=True)
        self.reasons.insert("1.0", "Blocked trades will list every rule that fired, one per line.")
        self.reasons.configure(state="disabled")

    def _num(self, label: str, fallback: float) -> float:
        try:
            return float(self.inputs[label].get())
        except ValueError:
            return fallback

    def _check(self) -> None:
        try:
            policy = RiskPolicy(account_equity=self._num("ACCOUNT EQUITY", 2000.0))
        except ValueError as exc:
            self._show_blocked([str(exc)])
            return

        day = DayState(
            losses=int(self._num("LOSSES TODAY", 0)),
            realized_pnl=float(self.realized.get() or 0),
            open_positions=int(self._num("OPEN POSITIONS", 0)),
        )
        decision = evaluate(
            policy=policy,
            day=day,
            side=Side(self.side.get()),
            entry=self._num("ENTRY", 0.0),
            stop=self._num("STOP", 0.0) or None,
            target=self._num("TARGET", 0.0) or None,
        )

        if decision.allowed:
            self.banner.configure(fg_color="#12251b", border_color=UP)
            self.verdict.configure(text="ALLOW", text_color=UP)
            self.verdict_detail.configure(
                text=f"{decision.contracts} contract(s)  |  risk {money(decision.risk_usd)}  |  "
                     f"reward {money(decision.reward_usd)}  |  R:R {decision.reward_risk:.2f}  |  "
                     f"stop {decision.stop_ticks:g} ticks",
                text_color=TEXT,
            )
            self._write_reasons(["All rules passed."])
        else:
            self._show_blocked(decision.reasons)

    def _show_blocked(self, reasons: list[str]) -> None:
        self.banner.configure(fg_color="#261315", border_color=DOWN)
        self.verdict.configure(text="BLOCK", text_color=DOWN)
        self.verdict_detail.configure(text=f"{len(reasons)} rule(s) refused this trade.",
                                      text_color=TEXT)
        self._write_reasons(reasons)

    def _write_reasons(self, reasons: list[str]) -> None:
        self.reasons.configure(state="normal")
        self.reasons.delete("1.0", "end")
        self.reasons.insert("1.0", "\n".join(f"-  {r}" for r in reasons))
        self.reasons.configure(state="disabled")


class JournalPage(ctk.CTkFrame):
    COLUMNS = ["Date", "Time", "Side", "Entry", "Exit", "Ticks", "P&L $", "Setup", "Plan"]

    def __init__(self, master) -> None:
        super().__init__(master, fg_color="transparent")
        self.path = Path("journal.csv")

        ctk.CTkLabel(self, text="Journal", font=("Segoe UI", 22, "bold"), text_color=TEXT).pack(
            anchor="w", pady=(0, 2)
        )
        ctk.CTkLabel(
            self, text="The same maths as the backtest, applied to what you actually did.",
            font=UI_SMALL, text_color=MUTED,
        ).pack(anchor="w", pady=(0, 14))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(
            bar, text="Open journal csv", width=150, height=34, command=self._choose,
            fg_color="#2a3040", hover_color="#343c50", text_color=TEXT,
        ).pack(side="left")
        ctk.CTkButton(
            bar, text="Refresh", width=100, height=34, command=self.refresh,
            fg_color=ACCENT, hover_color="#5b93e6", text_color="#0b1020", font=UI_BOLD,
        ).pack(side="left", padx=(8, 0))
        self.path_label = ctk.CTkLabel(bar, text="journal.csv", font=UI_SMALL, text_color=MUTED)
        self.path_label.pack(side="left", padx=(14, 0))

        stats_row = ctk.CTkFrame(self, fg_color="transparent", height=78)
        stats_row.pack(fill="x", pady=(0, 14))
        self.s_trades = stat_card(stats_row, "trades")
        self.s_win = stat_card(stats_row, "win rate")
        self.s_pf = stat_card(stats_row, "profit factor")
        self.s_pnl = stat_card(stats_row, "net p&l")
        self.s_plan = stat_card(stats_row, "plan followed")

        table_card = card(self)
        table_card.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Beans.Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
            borderwidth=0, rowheight=28, font=NUM_SMALL,
        )
        style.configure(
            "Beans.Treeview.Heading", background=CARD, foreground=MUTED, borderwidth=0,
            font=("Segoe UI", 10), relief="flat",
        )
        style.map("Beans.Treeview", background=[("selected", "#243044")])

        self.tree = ttk.Treeview(table_card, columns=self.COLUMNS, show="headings",
                                 style="Beans.Treeview")
        for column, width in zip(self.COLUMNS, (100, 70, 70, 90, 90, 80, 90, 130, 60)):
            self.tree.heading(column, text=column, anchor="w")
            self.tree.column(column, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

    def _choose(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose the journal csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if path:
            self.path = Path(path)
            self.path_label.configure(text=self.path.name)
            self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        try:
            report = analyse(self.path)
            rows = read_journal(self.path)
        except (OSError, ValueError) as exc:
            self.path_label.configure(text=str(exc), text_color=DOWN)
            return

        s = report.stats
        self.s_trades.configure(text=str(report.rows))
        self.s_win.configure(text=f"{s.win_rate:.1f}%")
        self.s_pf.configure(text=("inf" if s.profit_factor == float("inf")
                                  else f"{s.profit_factor:.2f}"))
        self.s_pnl.configure(text=money(s.total_pnl),
                             text_color=UP if s.total_pnl >= 0 else DOWN)
        self.s_plan.configure(
            text=f"{report.followed_plan_pct:.0f}%",
            text_color=UP if report.followed_plan_pct >= 70 else DOWN,
        )

        for row in rows[-200:]:
            self.tree.insert("", "end", values=(
                row.get("Date", ""), row.get("Time_IL", ""), row.get("Side", ""),
                row.get("EntryPrice", ""), row.get("ExitPrice", ""), row.get("Ticks", ""),
                row.get("PnL_USD", ""), row.get("Setup", ""), row.get("FollowedPlan(Y/N)", ""),
            ))


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Beans Desk")
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.configure(fg_color=BG)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, fg_color="#0b0d12", corner_radius=0, width=210)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="BEANS", font=("Segoe UI", 20, "bold"), text_color=TEXT).pack(
            anchor="w", padx=20, pady=(26, 0)
        )
        ctk.CTkLabel(sidebar, text="DESK", font=("Segoe UI", 20, "bold"), text_color=ACCENT).pack(
            anchor="w", padx=20, pady=(0, 26)
        )

        self.nav: dict[str, ctk.CTkButton] = {}
        for name in ("Backtest", "Risk gate", "Journal"):
            button = ctk.CTkButton(
                sidebar, text=name, anchor="w", height=40, corner_radius=8,
                fg_color="transparent", hover_color="#1b202b", text_color=MUTED,
                font=UI, command=lambda n=name: self.show(n),
            )
            button.pack(fill="x", padx=12, pady=2)
            self.nav[name] = button

        ctk.CTkLabel(
            sidebar, text=f"v{__version__}\nSoftware, not advice.\nNo orders are placed.",
            font=("Segoe UI", 10), text_color="#4b5265", justify="left",
        ).pack(side="bottom", anchor="w", padx=20, pady=18)

        container = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        container.grid(row=0, column=1, sticky="nsew", padx=22, pady=20)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.pages = {
            "Backtest": BacktestPage(container),
            "Risk gate": RiskPage(container),
            "Journal": JournalPage(container),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.show("Backtest")

    def show(self, name: str) -> None:
        for label, button in self.nav.items():
            active = label == name
            button.configure(
                fg_color="#171a21" if active else "transparent",
                text_color=TEXT if active else MUTED,
            )
        self.pages[name].tkraise()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
