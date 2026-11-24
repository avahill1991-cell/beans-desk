# beans-desk

A deterministic backtesting and risk-checking toolkit for futures traders.

- CSV in, metrics and a self-contained HTML tearsheet out.
- A pre-trade risk gate that returns ALLOW or BLOCK with the exact reasons.
- A trade journal that reports the same metrics on real fills.
- An optional desktop shell.

## Run

```bash
python -m beansdesk demo --out examples/sample_mzs.csv
python -m beansdesk backtest --data examples/sample_mzs.csv
python -m beansdesk risk-check --equity 2000 --entry 12.4000 --stop 12.3950 --target 12.4100
```

Tests:

```bash
python -m unittest discover -s tests -t .
```

Python 3.10+. The engine has no dependencies. `pip install customtkinter` is needed
only for `beansdesk gui`.

## Licence

All rights reserved. The source is published for reference only; no permission is
granted to use, copy, modify, or redistribute it. See `LICENSE`.
