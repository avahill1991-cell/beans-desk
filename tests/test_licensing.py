"""Licence key tests.

The point of these is not to prove the scheme is unbreakable. It is not, and the
module says so. They prove that a key issued by the seller verifies, that a
tampered key does not, and that an expired key stops working.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from beansdesk import licensing


class KeyTests(unittest.TestCase):
    def test_round_trip(self):
        key = licensing.make_key("Buyer@Example.com", plan="pro", days=30)
        info = licensing.verify_key(key)
        self.assertTrue(info.valid, info.reason)
        self.assertEqual(info.email, "buyer@example.com")
        self.assertEqual(info.plan, "pro")
        self.assertGreater(info.days_left, 0)

    def test_plan_is_preserved(self):
        info = licensing.verify_key(licensing.make_key("a@b.c", plan="studio", days=10))
        self.assertEqual(info.plan, "studio")

    def test_tampered_payload_fails(self):
        key = licensing.make_key("a@b.c", days=10)
        payload, signature = key.split(".")
        flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
        info = licensing.verify_key(f"{flipped}.{signature}")
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "signature does not match")

    def test_tampered_signature_fails(self):
        key = licensing.make_key("a@b.c", days=10)
        payload, signature = key.split(".")
        info = licensing.verify_key(f"{payload}.{'0' * len(signature)}")
        self.assertFalse(info.valid)

    def test_expired_key_is_invalid(self):
        key = licensing.make_key("a@b.c", days=1)
        later = date.today() + timedelta(days=2)
        info = licensing.verify_key(key, today=later)
        self.assertFalse(info.valid)
        self.assertEqual(info.reason, "expired")

    def test_expiry_boundary_still_valid_on_the_day(self):
        key = licensing.make_key("a@b.c", days=1)
        tomorrow = date.today() + timedelta(days=1)
        self.assertTrue(licensing.verify_key(key, today=tomorrow).valid)

    def test_garbage_input(self):
        for raw in ("", "   ", "no-dot-here", "a.b.c", "...."):
            with self.subTest(raw=raw):
                self.assertFalse(licensing.verify_key(raw).valid)

    def test_whitespace_is_tolerated(self):
        key = licensing.make_key("a@b.c", days=10)
        messy = f"  {key[:10]}\n{key[10:]}  "
        self.assertTrue(licensing.verify_key(messy).valid)

    def test_label_shows_trial_without_key(self):
        self.assertEqual(licensing.verify_key("").label, "TRIAL")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = licensing.APP_DIR
        licensing.APP_DIR = Path(self.tmp.name)

    def tearDown(self):
        licensing.APP_DIR = self.orig
        self.tmp.cleanup()

    def test_save_then_load(self):
        key = licensing.make_key("a@b.c", days=10)
        path = licensing.save_key(key)
        self.assertTrue(path.exists())
        self.assertEqual(licensing.load_key(), key)
        self.assertTrue(licensing.status().valid)

    def test_no_file_means_no_key(self):
        self.assertEqual(licensing.load_key(), "")
        self.assertFalse(licensing.status().valid)


if __name__ == "__main__":
    unittest.main()
