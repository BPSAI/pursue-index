"""Tests for the web-payload builder for novelty data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_novelty_data", REPO_ROOT / "scripts" / "build_novelty_data.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_emits_card_keyed_map(tmp_path: Path):
    src = tmp_path / "novelty.json"
    src.write_text(
        json.dumps(
            {
                "archive_id": "synthetic",
                "computed_at": "2026-05-09T00:00:00Z",
                "thresholds": {"high": 0.85, "partial": 0.7},
                "cards": [
                    {
                        "card_id": "abc",
                        "disclosure_status": "novel",
                        "novelty_score": 0.9,
                        "matches": [{"page": 1, "ref_archive": "synthetic", "similarity": 0.2}],
                    },
                    {
                        "card_id": "def",
                        "disclosure_status": "partial",
                        "novelty_score": 0.3,
                        "matches": [],
                    },
                ],
            }
        )
    )
    out = tmp_path / "web_novelty.json"
    mod = _load_module()
    rc = mod.build(src, out)
    assert rc == 0

    payload = json.loads(out.read_text())
    assert payload["archive_id"] == "synthetic"
    assert "abc" in payload["cards"]
    assert payload["cards"]["abc"]["disclosure_status"] == "novel"
    assert payload["cards"]["def"]["matches"] == []


def test_build_returns_nonzero_when_source_missing(tmp_path: Path):
    mod = _load_module()
    rc = mod.build(tmp_path / "nope.json", tmp_path / "out.json")
    assert rc == 1
