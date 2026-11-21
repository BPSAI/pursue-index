"""``/deploy-stamp.json`` must reach the static assets, not a Worker route.

The post-deploy verify reads the stamp from the live site, so routing has to
hand it to the assets binding: no ``routes`` pattern that would send it
elsewhere, the stamp lands in the assets directory, and no Worker route claims
the path (the Worker's own handlers key on ``/api/``, ``/pdf/``, ``/video/``,
``/archive/`` and ``/card/``; everything else falls through to ``ASSETS``).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STAMP_PATH = "/deploy-stamp.json"


def _wrangler() -> dict:
    text = (ROOT / "wrangler.jsonc").read_text()
    text = re.sub(r'("(?:[^"\\]|\\.)*")|//[^\n]*', lambda m: m.group(1) or "", text)  # strip // comments
    return json.loads(text)


def test_wrangler_serves_assets_from_the_build_output_through_the_worker():
    cfg = _wrangler()
    assets = cfg["assets"]
    assert assets["directory"] == "./web/dist" and assets["binding"] == "ASSETS"
    assert cfg["main"] == "./worker/index.js"
    # worker-first means the Worker sees the request, then falls through to ASSETS
    assert assets["run_worker_first"] is True


def test_no_route_pattern_diverts_the_stamp_path():
    cfg = _wrangler()
    patterns = [r if isinstance(r, str) else r.get("pattern", "") for r in cfg.get("routes", [])]
    assert all(p.endswith("/*") or "deploy-stamp" not in p for p in patterns)
    assert "route" not in cfg or "deploy-stamp" not in json.dumps(cfg["route"])


def test_stamp_is_written_into_the_assets_directory():
    writer = (ROOT / "web" / "scripts" / "write_deploy_stamp.mjs").read_text()
    assert '"../public/deploy-stamp.json"' in writer  # public/ is copied verbatim into web/dist
    assert "deploy-stamp.json" in (ROOT / ".gitignore").read_text()  # generated, never committed


def test_worker_route_matchers_do_not_claim_the_stamp_path():
    src = (ROOT / "worker" / "index.js").read_text()
    api = re.search(r"WORKER_API_PATHS\s*=\s*new Set\(\[(.*?)\]\)", src, re.S).group(1)
    assert STAMP_PATH not in api
    pdf = (ROOT / "worker" / "pdf.js").read_text()
    for prefix in re.findall(r'pathname\.startsWith\("([^"]+)"\)', pdf):
        assert not STAMP_PATH.startswith(prefix), prefix
    aliases = (ROOT / "worker" / "aliases.js").read_text()
    card_re = re.search(r"CARD_PATH_RE\s*=\s*/(.+)/;", aliases).group(1)
    assert re.search(card_re.replace("\\/", "/"), STAMP_PATH) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_worker_hands_the_stamp_request_to_the_assets_binding():
    res = subprocess.run(["node", "--test", "tests/deploy_stamp_route.test.js"], cwd=ROOT / "worker",
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
