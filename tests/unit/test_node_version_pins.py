"""One Node version for every place the site is built.

``web/package.json`` declares the Node floor in ``engines`` and ``web/.npmrc``
sets ``engine-strict``, so an older Node fails ``npm install`` outright. CI
reads the version from ``web/.nvmrc`` (``setup-node`` ``node-version-file``).
The Cloudflare Workers build runs ``cd web && npm install`` from the repo root,
and reads ``.node-version`` from that root. The pins must agree, and must meet
the floor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ver(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def test_root_node_version_matches_web_nvmrc() -> None:
    root_pin = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    web_pin = (ROOT / "web" / ".nvmrc").read_text(encoding="utf-8").strip()
    assert root_pin == web_pin


def test_the_pin_meets_the_engines_floor() -> None:
    engines = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["engines"]
    floor = _ver(engines["node"])
    pin = _ver((ROOT / "web" / ".nvmrc").read_text(encoding="utf-8"))
    assert pin >= floor, (pin, floor)


def test_engine_strict_is_on() -> None:
    npmrc = (ROOT / "web" / ".npmrc").read_text(encoding="utf-8")
    assert re.search(r"^engine-strict=true$", npmrc, re.M)


def test_every_workflow_that_installs_web_deps_reads_the_pin() -> None:
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        if not re.search(r"npm (ci|install)|npm audit", text):
            continue
        assert "node-version-file: web/.nvmrc" in text, wf.name
        assert not re.search(r"node-version:\s", text), wf.name
