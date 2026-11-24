"""Market data sources.

One rule: this module is the only place that knows about the outside world.
Everything downstream receives `Bar` objects in dollars per bushel, already clean.

Yahoo quotes CBOT futures in **cents** per bushel (ZS=F at 1220.75 means $12.2075).
The conversion happens here, once, so no other part of the app has to think about it.
"""

from __future__ import annotations

import csv
import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from beansdesk.data import Bar

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CACHE_DIR = Path("data") / "cache"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchResult:
    symbol: str
    bars: list[Bar]
    source: str
    from_cache: bool
    note: str = ""


def _cache_paths(symbol: str, range_: str, interval: str) -> tuple[Path, Path]:
    safe = symbol.replace("=", "_").replace("/", "_").replace("^", "_")
    stem = f"{safe}_{range_}_{interval}"
    return CACHE_DIR / f"{stem}.csv", CACHE_DIR / f"{stem}.json"


def _write_cache(symbol: str, range_: str, interval: str, bars: list[Bar]) -> None:
    csv_path, meta_path = _cache_paths(symbol, range_, interval)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            writer.writerow([b.date.isoformat(), b.open, b.high, b.low, b.close, b.volume])
    meta_path.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "range": range_,
                "interval": interval,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rows": len(bars),
                "first": bars[0].date.isoformat() if bars else None,
                "last": bars[-1].date.isoformat() if bars else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _read_cache(symbol: str, range_: str, interval: str) -> list[Bar]:
    csv_path, _ = _cache_paths(symbol, range_, interval)
    bars: list[Bar] = []
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            bars.append(
                Bar(
                    date=datetime.strptime(row["date"], "%Y-%m-%d").date(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"] or 0),
                )
            )
    return bars


def _get_json(url: str, timeout: float = 30.0) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_yahoo(
    symbol: str,
    range_: str = "10y",
    interval: str = "1d",
    *,
    refresh: bool = False,
    timeout: float = 30.0,
) -> FetchResult:
    """Download daily bars for a Yahoo symbol, cached on disk.

    Prices come back in cents for futures; they are divided by 100 here.
    """
    csv_path, _ = _cache_paths(symbol, range_, interval)
    if csv_path.exists() and not refresh:
        bars = _read_cache(symbol, range_, interval)
        if bars:
            return FetchResult(symbol, bars, "yahoo", True, "from local cache")

    url = YAHOO.format(symbol=urllib.parse.quote(symbol)) + f"?range={range_}&interval={interval}"
    try:
        payload = _get_json(url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError) as exc:
        if csv_path.exists():
            bars = _read_cache(symbol, range_, interval)
            return FetchResult(symbol, bars, "yahoo", True, f"offline, using cache ({exc})")
        raise ConnectionError(f"could not reach Yahoo Finance: {exc}") from exc

    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"yahoo error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise ValueError(f"no data returned for {symbol}")

    result = results[0]
    meta = result.get("meta") or {}
    offset = timedelta(seconds=int(meta.get("gmtoffset") or 0))
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]

    rows: list[Bar] = []
    for i, stamp in enumerate(stamps):
        try:
            o, h, l, c = (quote[k][i] for k in ("open", "high", "low", "close"))
        except (KeyError, IndexError, TypeError):
            continue
        if None in (o, h, l, c):
            continue
        volume = quote.get("volume", [0] * len(stamps))[i] or 0
        day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(
            timezone(offset)
        ).date()
        rows.append(Bar(day, float(o), float(h), float(l), float(c), float(volume)))

    if not rows:
        raise ValueError(f"{symbol}: every bar was empty")

    note = "cents converted to dollars"
    if statistics.median(b.close for b in rows) > 50:
        rows = [Bar(b.date, b.open / 100, b.high / 100, b.low / 100, b.close / 100, b.volume)
                for b in rows]
    else:
        note = "prices already in dollars"

    rows.sort(key=lambda b: b.date)
    _write_cache(symbol, range_, interval, rows)
    return FetchResult(symbol, rows, "yahoo", False, note)


def write_csv(bars: list[Bar], path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "open", "high", "low", "close", "volume"])
        for b in bars:
            writer.writerow(
                [b.date.isoformat(), f"{b.open:.4f}", f"{b.high:.4f}",
                 f"{b.low:.4f}", f"{b.close:.4f}", int(b.volume)]
            )
    return out
