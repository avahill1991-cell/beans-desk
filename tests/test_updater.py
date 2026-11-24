"""Update manifest tests. No network: every check reads a local json file."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from beansdesk import updater


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("v0.10.0"), (0, 10, 0))
        self.assertEqual(updater.parse_version("2"), (2,))

    def test_parse_is_numeric_not_lexicographic(self):
        self.assertGreater(updater.parse_version("0.10.0"), updater.parse_version("0.9.9"))

    def test_parse_garbage_does_not_raise(self):
        self.assertEqual(updater.parse_version(""), (0,))
        self.assertEqual(updater.parse_version("banana"), (0,))


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, **data) -> Path:
        path = self.dir / "version.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_newer_version_is_available(self):
        path = self.manifest(version="0.2.0", url="https://example.com/x.exe", notes="fixes")
        info = updater.check("0.1.0", str(path))
        self.assertTrue(info.available)
        self.assertEqual(info.latest, "0.2.0")
        self.assertEqual(info.url, "https://example.com/x.exe")
        self.assertEqual(info.notes, "fixes")

    def test_same_version_is_not_available(self):
        path = self.manifest(version="0.1.0")
        self.assertFalse(updater.check("0.1.0", str(path)).available)

    def test_older_manifest_is_not_available(self):
        path = self.manifest(version="0.0.9")
        self.assertFalse(updater.check("0.1.0", str(path)).available)

    def test_missing_manifest_reports_error_not_exception(self):
        info = updater.check("0.1.0", str(self.dir / "nope.json"))
        self.assertFalse(info.available)
        self.assertIn("not found", info.error)

    def test_manifest_without_version_reports_error(self):
        path = self.manifest(url="x")
        info = updater.check("0.1.0", str(path))
        self.assertFalse(info.available)
        self.assertIn("no version", info.error)

    def test_broken_json_reports_error(self):
        path = self.dir / "version.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertFalse(updater.check("0.1.0", str(path)).available)


if __name__ == "__main__":
    unittest.main()
