"""The web toolchain's Cloudflare packages stay on stable releases.

wrangler 4.12x+ depends on a ``5.x-beta`` miniflare. The pin below keeps a
wrangler whose miniflare is a stable release, with the fixed undici and sharp
forced under it through scoped overrides.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "web" / "package.json"
LOCK = ROOT / "web" / "package-lock.json"

STABLE = re.compile(r"^\d+\.\d+\.\d+$")


def _lock_version(lock: dict, name: str) -> str:
    return lock["packages"][f"node_modules/{name}"]["version"]


def test_wrangler_is_pinned_exactly() -> None:
    spec = json.loads(PKG.read_text(encoding="utf-8"))["devDependencies"]["wrangler"]
    assert STABLE.match(spec), spec  # no ^ or ~, so it can't float to a beta miniflare


def test_miniflare_in_the_lockfile_is_stable() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    ver = _lock_version(lock, "miniflare")
    assert STABLE.match(ver), ver
    assert not re.search(r"alpha|beta|rc", ver)


def test_miniflare_undici_is_not_a_vulnerable_7x() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    nested = lock["packages"].get("node_modules/miniflare/node_modules/undici")
    ver = nested["version"] if nested else _lock_version(lock, "undici")
    major, minor, patch = (int(x) for x in ver.split(".")[:3])
    assert (major, minor, patch) >= (7, 30, 1), ver  # advisories cover 7.0.0 - 7.30.0


def test_scoped_overrides_force_the_fixed_undici_and_sharp() -> None:
    ov = json.loads(PKG.read_text(encoding="utf-8"))["overrides"]["miniflare"]
    assert ov["undici"] and ov["sharp"]
