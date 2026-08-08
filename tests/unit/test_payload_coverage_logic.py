"""Unit tests for the derived-payload coverage comparison engine.

The engine is exercised here on synthetic data so the semantics
(missing / extra / bounded reporting) are pinned independently of the
repo's real payloads. The repo-level gate lives in
``tests/integration/test_derived_payload_coverage.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support.payload_coverage import (
    PayloadSpec,
    describe_failure,
    evaluate,
    json_loader,
)


def _spec(**overrides: Any) -> PayloadSpec:
    """A minimal spec over one source file, easy to override per test."""
    base: dict[str, Any] = {
        "payload": "payload.json",
        "sources": ("source.json",),
        "eligible": lambda src: set(src["source.json"]),
        "shipped": lambda doc: set(doc),
        "require_no_missing": True,
        "require_no_extra": True,
        "key_label": "id",
        "rationale": "test spec",
    }
    base.update(overrides)
    return PayloadSpec(**base)


def _loader(payload: Any, source: Any):
    return lambda rel: {"payload.json": payload, "source.json": source}[rel]


def test_evaluate_reports_eligible_entries_absent_from_the_payload() -> None:
    """An eligible key the artifact never shipped is reported as missing."""
    result = evaluate(_spec(), _loader(payload=["a"], source=["a", "b", "c"]))

    assert result.missing == ["b", "c"]
    assert result.eligible_count == 3
    assert result.shipped_count == 1
    assert not result.ok


def test_evaluate_is_clean_when_the_payload_matches_the_predicate() -> None:
    result = evaluate(_spec(), _loader(payload=["a", "b"], source=["b", "a"]))

    assert result.missing == []
    assert result.extra == []
    assert result.ok


def test_evaluate_reports_shipped_entries_the_predicate_no_longer_admits() -> None:
    """Stale rows left behind by a partial rebuild surface as extras."""
    result = evaluate(_spec(), _loader(payload=["a", "b", "z"], source=["a", "b"]))

    assert result.extra == ["z"]
    assert result.missing == []
    assert not result.ok


def test_coverage_only_specs_tolerate_extras() -> None:
    """A superset spec gates on missing entries and ignores extras."""
    spec = _spec(require_no_extra=False)

    result = evaluate(spec, _loader(payload=["a", "z"], source=["a", "b"]))

    assert result.missing == ["b"]
    assert result.extra == []


def test_structural_specs_tolerate_missing_entries() -> None:
    """A subset spec gates only on entries with no source of record."""
    spec = _spec(require_no_missing=False)

    result = evaluate(spec, _loader(payload=["a", "z"], source=["a", "b"]))

    assert result.missing == []
    assert result.extra == ["z"]


def test_failure_message_names_ids_up_to_the_bound_then_counts_the_rest() -> None:
    """A red gate nobody can diagnose is a red gate that gets bypassed."""
    source = [f"card{i:02d}" for i in range(25)]
    result = evaluate(_spec(), _loader(payload=[], source=source))

    message = describe_failure(result, limit=20)

    assert "MISSING from payload (25)" in message
    assert "card00" in message and "card19" in message
    assert "card20" not in message
    assert "(+5 more)" in message
    assert "payload.json" in message
    assert "make rebuild-derivatives" in message


def test_json_loader_reads_repo_relative_paths_once(tmp_path: Path) -> None:
    """pages.json is 16 MB and feeds several specs — parse it once."""
    target = tmp_path / "web" / "public" / "data"
    target.mkdir(parents=True)
    (target / "pages.json").write_text(json.dumps(["first"]))

    load = json_loader(tmp_path)
    first = load("web/public/data/pages.json")
    (target / "pages.json").write_text(json.dumps(["second"]))

    assert first == ["first"]
    assert load("web/public/data/pages.json") == ["first"]
    assert json_loader(tmp_path)("web/public/data/pages.json") == ["second"]


def test_failure_message_renders_tuple_keys_and_stale_rows() -> None:
    spec = _spec(key_label="(card_id, page)")
    result = evaluate(spec, _loader(payload=[("c1", 2)], source=[("c1", 1)]))

    message = describe_failure(result)

    assert "c1:1" in message  # missing (card_id, page)
    assert "STALE in payload, no longer eligible (1): c1:2" in message
