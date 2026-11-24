"""Data source tests.

No network in the test suite. The Yahoo response is faked at the `_get_json`
boundary, which is also the only place a network error can come from.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from beansdesk import sources


def fake_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": 0},
                    "timestamp": [1704067200, 1704153600, 1704240000],
                    "indicators": {
                        "quote": [
                            {
                                "open": [1220.0, 1221.0, None],
                                "high": [1225.0, 1226.0, 1227.0],
                                "low": [1215.0, 1216.0, 1217.0],
                                "close": [1220.75, 1221.50, 1222.0],
                                "volume": [1000, 2000, 3000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_cache = sources.CACHE_DIR
        self._orig_get = sources._get_json
        sources.CACHE_DIR = Path(self.tmp.name) / "cache"
        self.calls = 0

        def fake_get(url: str, timeout: float = 30.0) -> dict:
            self.calls += 1
            return fake_payload()

        sources._get_json = fake_get

    def tearDown(self) -> None:
        sources.CACHE_DIR = self._orig_cache
        sources._get_json = self._orig_get
        self.tmp.cleanup()

    def test_cents_are_converted_to_dollars(self):
        result = sources.fetch_yahoo("ZS=F", "1y")
        self.assertAlmostEqual(result.bars[0].close, 12.2075)
        self.assertAlmostEqual(result.bars[0].high, 12.25)
        self.assertLess(result.bars[0].close, 50, "prices should be dollars, not cents")

    def test_empty_bars_are_dropped(self):
        result = sources.fetch_yahoo("ZS=F", "1y")
        self.assertEqual(len(result.bars), 2, "the bar with a null open must be skipped")

    def test_second_call_uses_the_cache(self):
        first = sources.fetch_yahoo("ZS=F", "1y")
        second = sources.fetch_yahoo("ZS=F", "1y")
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(self.calls, 1, "cache hit must not hit the network")
        self.assertEqual(len(first.bars), len(second.bars))

    def test_refresh_bypasses_the_cache(self):
        sources.fetch_yahoo("ZS=F", "1y")
        sources.fetch_yahoo("ZS=F", "1y", refresh=True)
        self.assertEqual(self.calls, 2)

    def test_write_csv_round_trip(self):
        from beansdesk.data import load_bars

        result = sources.fetch_yahoo("ZS=F", "1y")
        out = sources.write_csv(result.bars, Path(self.tmp.name) / "out.csv")
        reloaded = load_bars(out)
        self.assertEqual(len(reloaded), len(result.bars))
        self.assertAlmostEqual(reloaded[0].close, result.bars[0].close, places=4)

    def test_error_payload_raises(self):
        sources._get_json = lambda url, timeout=30.0: {"chart": {"error": "boom", "result": None}}
        with self.assertRaises(ValueError):
            sources.fetch_yahoo("NOPE", "1y")

    def test_offline_with_cache_falls_back(self):
        sources.fetch_yahoo("ZS=F", "1y")

        def dead(url: str, timeout: float = 30.0) -> dict:
            raise sources.urllib.error.URLError("no network")

        sources._get_json = dead
        result = sources.fetch_yahoo("ZS=F", "1y", refresh=True)
        self.assertTrue(result.from_cache)
        self.assertIn("offline", result.note)

    def test_offline_without_cache_raises(self):
        def dead(url: str, timeout: float = 30.0) -> dict:
            raise sources.urllib.error.URLError("no network")

        sources._get_json = dead
        with self.assertRaises(ConnectionError):
            sources.fetch_yahoo("ZS=F", "1y")


if __name__ == "__main__":
    unittest.main()
