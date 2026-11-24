"""Generate the example dataset.

    python tools/make_sample_data.py [out.csv] [bars] [seed]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beansdesk.sample import generate  # noqa: E402

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "examples/sample_mzs.csv"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 520
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    print(generate(out, bars=bars, seed=seed))
