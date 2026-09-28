"""``scripts/draft_display_dates.py`` reads pages.json through the shared
chunk-aware reader, and its per-card bookkeeping is unit-testable without
the model client."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pursue_index.release.chunked_asset import write_asset

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "draft_display_dates.py"


def _mod():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("draft_display_dates", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pages_by_card_reads_a_chunked_pages_json(tmp_path: Path) -> None:
    rows = [{"card_id": f"c{i % 3}", "page": i, "text": "é" * 20} for i in range(12)]
    path = tmp_path / "pages.json"
    write_asset(path, json.dumps(rows, ensure_ascii=False).encode("utf-8"), budget=200)
    assert not path.exists(), "fixture must be published as parts"
    by_card = _mod()._load_pages_by_card(path)
    assert sorted(by_card) == ["c0", "c1", "c2"]
    assert [p["page"] for p in by_card["c1"]] == [1, 4, 7, 10]


def test_proposal_record_pins_card_id_and_provenance() -> None:
    result = {
        "input": {"card_id": "rewritten", "display_date": "1947"},
        "usage": {"input_tokens": 3, "output_tokens": 2,
                  "cache_creation_input_tokens": 1, "cache_read_input_tokens": 0},
    }
    rec = _mod()._proposal_record("c9", result, "model-x")
    assert rec["card_id"] == "c9"
    assert rec["display_date"] == "1947"
    assert rec["display_date_curator"] == "agent-model-x"
    assert rec["display_date_approved_at"] is None
    assert rec["_proposal_metadata"]["input_tokens"] == 3
