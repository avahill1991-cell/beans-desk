"""Offline licence keys.

Key format:

    base64url(payload) + "." + base64url(hmac_sha256(SECRET, base64url(payload)))[:24]

Payload is JSON: {"e": email, "p": plan, "x": "YYYY-MM-DD"}.

Honest limitation, written down on purpose: the SECRET ships inside the binary, so
anyone who really wants to forge a key can extract it. This stops casual sharing and
key generators copied off a forum. It is not DRM. Server-side validation against
Lemon Squeezy's licence API is the v2 answer, and it needs a network round trip that
this product should not require to open a backtest.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

# Set BEANSDESK_LICENSE_SECRET at build time. The fallback exists so tests and local
# builds work; a release built with it can be forged by anyone holding the binary.
SECRET = os.environ.get(
    "BEANSDESK_LICENSE_SECRET", "dev-only-secret-not-for-release"
).encode("utf-8")

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "BeansDesk"


@dataclass(frozen=True)
class Licence:
    email: str
    plan: str
    expires: date
    valid: bool
    reason: str = ""

    @property
    def days_left(self) -> int:
        return (self.expires - date.today()).days

    @property
    def label(self) -> str:
        if not self.valid:
            return "TRIAL"
        return f"{self.plan.upper()} - {self.email}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload_b64: str) -> str:
    digest = hmac.new(SECRET, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64(digest)[:24]


def make_key(email: str, plan: str = "pro", days: int = 365) -> str:
    """Seller-side only. Never call this from the shipped app."""
    payload = {
        "e": email.strip().lower(),
        "p": plan,
        "x": (date.today() + timedelta(days=days)).isoformat(),
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{encoded}.{_sign(encoded)}"


def verify_key(key: str, today: date | None = None) -> Licence:
    today = today or date.today()
    cleaned = (key or "").strip().replace("\n", "").replace(" ", "")
    if not cleaned:
        return Licence("", "", today, False, "no key")
    if cleaned.count(".") != 1:
        return Licence("", "", today, False, "malformed key")

    payload_b64, signature = cleaned.split(".")
    if not hmac.compare_digest(_sign(payload_b64), signature):
        return Licence("", "", today, False, "signature does not match")

    try:
        payload = json.loads(_unb64(payload_b64))
        expires = datetime.strptime(payload["x"], "%Y-%m-%d").date()
    except (ValueError, KeyError, TypeError):
        return Licence("", "", today, False, "payload unreadable")

    if expires < today:
        return Licence(payload.get("e", ""), payload.get("p", ""), expires, False, "expired")

    return Licence(payload.get("e", ""), payload.get("p", "pro"), expires, True)


def key_path() -> Path:
    return APP_DIR / "license.key"


def save_key(key: str) -> Path:
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip(), encoding="utf-8")
    return path


def load_key() -> str:
    path = key_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def status() -> Licence:
    return verify_key(load_key())
