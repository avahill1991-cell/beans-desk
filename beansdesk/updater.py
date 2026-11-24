"""Update check against a static manifest.

There is no server yet, and there does not need to be one. A JSON file anywhere
(GitHub raw, an S3 object, a folder on disk) is enough:

    {"version": "0.2.0",
     "url": "https://example.com/BeansDesk-0.2.0.exe",
     "notes": "commission model fix"}

The app only reads it and tells the user. It never downloads or runs anything by
itself, which keeps the security story simple and honest.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MANIFEST_URL = "https://raw.githubusercontent.com/CHANGE-ME/beans-desk/main/version.json"


@dataclass(frozen=True)
class UpdateInfo:
    available: bool
    current: str
    latest: str
    url: str = ""
    notes: str = ""
    error: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for chunk in (text or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _load(manifest: str, timeout: float) -> dict:
    if manifest.startswith(("http://", "https://")):
        request = urllib.request.Request(manifest, headers={"User-Agent": "BeansDesk"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    path = Path(manifest)
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest}")
    return json.loads(path.read_text(encoding="utf-8"))


def check(current: str, manifest: str = MANIFEST_URL, timeout: float = 10.0) -> UpdateInfo:
    try:
        data = _load(manifest, timeout)
    except Exception as exc:  # noqa: BLE001 - offline is a normal outcome
        return UpdateInfo(False, current, current, error=str(exc))

    latest = str(data.get("version", "")).strip()
    if not latest:
        return UpdateInfo(False, current, current, error="manifest has no version")

    return UpdateInfo(
        available=parse_version(latest) > parse_version(current),
        current=current,
        latest=latest,
        url=str(data.get("url", "")),
        notes=str(data.get("notes", "")),
    )
