"""Self-contained HTML tearsheet.

No CDN, no JS, no external fonts. One file the user can email to themselves, open
on a phone, or print. That constraint is the feature: a report that needs the
internet to render is a report that will be broken in two years.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from beansdesk.backtest import BacktestResult

_CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#252a35;--text:#e6e8ee;--muted:#8b93a7;
--up:#35d07f;--down:#ff5d5d;--accent:#6ea8fe}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif;padding:32px}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:24px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.stat .v{font:600 20px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;margin-top:4px}
.pos{color:var(--up)}.neg{color:var(--down)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:24px}
.panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
margin:0 0 12px;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;
letter-spacing:.05em;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid rgba(37,42,53,.6);
font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
td.l{font-family:inherit}
tr:last-child td{border-bottom:none}
.foot{color:var(--muted);font-size:11px;line-height:1.7;margin-top:8px}
"""


def _svg_curve(equity: list[float], width: int = 900, height: int = 240) -> str:
    if len(equity) < 2:
        return "<p style='color:#8b93a7'>Not enough data to draw a curve.</p>"

    pad = 18
    lo, hi = min(equity), max(equity)
    span = (hi - lo) or 1.0
    step = (width - 2 * pad) / (len(equity) - 1)

    def y(value: float) -> float:
        return height - pad - (value - lo) / span * (height - 2 * pad)

    points = " ".join(f"{pad + i * step:.1f},{y(v):.1f}" for i, v in enumerate(equity))
    base_y = y(equity[0])
    area = f"{pad},{height - pad} {points} {pad + (len(equity) - 1) * step:.1f},{height - pad}"
    colour = "#35d07f" if equity[-1] >= equity[0] else "#ff5d5d"

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="Equity curve">'
        f'<line x1="{pad}" y1="{base_y:.1f}" x2="{width - pad}" y2="{base_y:.1f}" '
        f'stroke="#3a4152" stroke-width="1" stroke-dasharray="4 4"/>'
        f'<polygon points="{area}" fill="{colour}" opacity="0.10"/>'
        f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2" '
        f'stroke-linejoin="round"/>'
        f"</svg>"
    )


def render_report(result: BacktestResult, title: str = "Backtest report") -> str:
    s = result.stats
    cfg = result.config

    def money(value: float) -> str:
        cls = "pos" if value > 0 else ("neg" if value < 0 else "")
        return f'<span class="{cls}">${value:,.2f}</span>'

    stats_html = "".join(
        f'<div class="stat"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>'
        for k, v in s.as_rows()
    )

    trade_rows = "".join(
        "<tr>"
        f"<td>{t.entry_date}</td>"
        f'<td class="l">{t.side.value.upper()}</td>'
        f"<td>{t.entry:.2f}</td>"
        f"<td>{t.exit:.2f}</td>"
        f"<td>{t.ticks:+.2f}</td>"
        f"<td>{t.pnl:+.2f}</td>"
        f'<td class="l">{html.escape(t.reason)}</td>'
        "</tr>"
        for t in result.trades[-60:]
    ) or '<tr><td colspan="7" class="l" style="color:#8b93a7">No trades generated.</td></tr>'

    first, last = result.bars[0].date, result.bars[-1].date
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{html.escape(title)}</h1>
<div class="sub">{first} to {last} &middot; {len(result.bars)} bars &middot;
{cfg.fast}/{cfg.slow} SMA &middot; {cfg.stop_ticks} tick stop &middot;
{cfg.reward_risk:g}R target &middot; {cfg.contracts} contract(s)</div>

<div class="grid">{stats_html}</div>

<div class="panel"><h2>Equity curve</h2>{_svg_curve(result.equity)}
<div class="foot">Start equity ${cfg.start_equity:,.2f}. Ties between stop and target
are resolved as a stop fill, so the curve is pessimistic by construction.</div></div>

<div class="panel"><h2>Last {min(len(result.trades), 60)} of {len(result.trades)} trades</h2>
<table><thead><tr><th>Entry</th><th>Side</th><th>In</th><th>Out</th>
<th>Ticks</th><th>P&amp;L $</th><th>Exit</th></tr></thead>
<tbody>{trade_rows}</tbody></table></div>

<div class="foot">Net {money(s.total_pnl)} over {s.trades} trades.
Generated {generated} by Beans Desk.<br>
Historical simulation on data you supplied. Not a prediction, not advice, and no
claim about future results.</div>
</div></body></html>
"""


def write_report(result: BacktestResult, path: str | Path, title: str = "Backtest report") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_report(result, title), encoding="utf-8")
    return p
