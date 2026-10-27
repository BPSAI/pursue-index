"""R7C.31 acceptance: replay the 096ef poll and check the record it writes.

``scripts/poll_snapshot.py`` runs as the snapshot job runs it, on the real
Release-7 inputs, with only the network stubbed (``tests/support/
tranche_ready_096ef``). The record must validate against the vendored
schema and match the pinned example (``tests/fixtures/
tranche-ready-096ef.json``) on every field the replay's inputs determine.

Fields that cannot match, and why, are listed in ``_NOT_REPRODUCIBLE``; each
is asserted against its own source instead:

* ``example_provenance`` exists only on the reference example;
* ``detected_at``/``generated_at`` are the run's clock;
* ``supersedes[].issue`` -- the flapped sha's issue number (#176) is not in
  any committed input; the record carries null;
* D042's byte shas, sizes and ``evidence.appended_bytes`` -- the fixture
  bytes are synthetic (the real PDFs are not committed), so they are checked
  against the served fixture bytes; ``evidence`` carries only what
  ``classify_bytes`` and a prefix check establish (no changed-object list,
  no text/render comparison);
* the worst-case figures (``high_usd``, per-stage ``high_*``) -- the record
  prices them from ``release/rates.py``, whose ceilings differ from the
  example's; checked against ``rates`` instead.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from pursue_index.release import rates
from pursue_index.tranche_ready.schema import load_schema, validate
from tests.support.tranche_096ef import D042_NEW_ID, D042_OLD_ID, REPO_ROOT, receipt
from tests.support.tranche_ready_096ef import VECTOR, d042_bytes, fake_http_get, run_replay, sha256

if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

_CANDIDATE_BYTES = ("old_byte_sha256", "new_byte_sha256", "old_byte_size", "new_byte_size",
                    "evidence")


def _strip(record: dict) -> dict:
    out = copy.deepcopy(record)
    for key in ("example_provenance", "detected_at", "generated_at"):
        out.pop(key, None)
    for sup in out["supersedes"]:
        sup.pop("issue", None)
    for cand in out["candidates"]:
        for key in _CANDIDATE_BYTES:
            cand.pop(key, None)
    out["estimate"].pop("high_usd")
    for stage in out["estimate"]["per_stage"]:
        stage.pop("high_rate_per_page")
        stage.pop("high_usd")
    return out


@pytest.fixture(scope="module")
def replay(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("replay")
    assert run_replay(tmp, fake_http_get()) == 0
    return tmp


@pytest.fixture(scope="module")
def replay_old_unreachable(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("replay-old-unreachable")
    assert run_replay(tmp, fake_http_get(old_fetch_ok=False)) == 0
    return tmp


def _record(tmp: Path) -> dict:
    return json.loads((tmp / "tranche-ready" / "096ef2c0058a.json").read_text())


def test_replay_record_validates_and_matches_the_example(replay: Path) -> None:
    record = _record(replay)
    assert validate(record, load_schema()) == []
    assert _strip(record) == _strip(json.loads(VECTOR.read_text()))


def test_replay_carries_d042_as_metadata_only_on_the_fixture_bytes(replay: Path) -> None:
    old, new = d042_bytes()
    [cand] = _record(replay)["candidates"]
    assert (cand["old_card_id"], cand["new_card_id"]) == (D042_OLD_ID, D042_NEW_ID)
    assert cand["byte_verdict"] == "metadata-only" and cand["stop_and_ask"] is False
    assert (cand["old_byte_sha256"], cand["new_byte_sha256"]) == (sha256(old), sha256(new))
    assert (cand["old_byte_size"], cand["new_byte_size"]) == (len(old), len(new))
    assert cand["evidence"] == {"old_prefix_of_new": True, "appended_bytes": len(new) - len(old),
                                "incremental_update": True}


def test_replay_prices_the_worst_case_from_the_rates_table(replay: Path) -> None:
    est = _record(replay)["estimate"]
    band = rates.cost_band(1140, judge=rates.JudgeRate(0.0165, rates.JUDGE_METERED))
    assert [s["high_usd"] for s in est["per_stage"]] == [
        round(s.high, 2) for s in band.stages.values()]
    assert est["recommended_cap_usd"] == 55.0 < est["high_usd"]


def test_replay_with_old_bytes_unreachable_has_no_verdict_and_stops(
    replay_old_unreachable: Path,
) -> None:
    record = _record(replay_old_unreachable)
    assert validate(record, load_schema()) == []
    [cand] = record["candidates"]
    assert cand["byte_verdict"] is None and cand["byte_verdict_reason"] == "old_fetch_failed"
    assert cand["stop_and_ask"] is True and cand["evidence"] is None
    assert record["status"] == "stop-and-ask"
    assert any(D042_NEW_ID in r for r in record["stop_reasons"])
    assert record["fetch"]["old_failed"] == 1 and record["fetch"]["old_fetched"] == 0
    assert {"card_id": D042_NEW_ID, "reason": "quarantined-new", "doc_id": "DOW-UAP-D042"} in (
        record["scope"]["cards"])


def test_replay_commits_the_tranche_diff_with_the_byte_evidence(replay: Path) -> None:
    out = replay / "tranche-diffs" / "tranche-diff-096ef2c0058a"
    diff = json.loads(out.with_suffix(".json").read_text())
    assert out.with_suffix(".md").exists()
    assert diff["summary"] == receipt()["summary"]
    [row] = diff["quarantined"]
    assert row["resave_evidence"]["change_nature"] == "metadata-only"
    assert all(r["byte_sha256"] for r in diff["new_content"])


def test_replay_leaves_no_pdf_bytes_behind(replay: Path) -> None:
    assert list(replay.rglob("*.pdf")) == []
