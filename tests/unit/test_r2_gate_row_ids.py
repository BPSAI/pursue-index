"""The drift gate keys on stable row ids, not file position; an old integer marker rescans all."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_drift_scan  # noqa: E402
import _r2_run_state  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, sha, url  # noqa: E402

NOW = datetime.now(UTC)


def _row(cid, body, days_ago, n=1):
    return {
        "card_id": cid, "asset_url": url(n), "asset_filename": f"c{n}.pdf",
        "byte_sha256": sha(body), "byte_size": len(body),
        "fetched_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def _args(tmp_path, registry_rows, fail_on_drift=True):
    registry = tmp_path / "registry.jsonl"
    registry.write_text("".join(json.dumps(r) + "\n" for r in registry_rows))
    return SimpleNamespace(
        registry=registry, gate_marker=tmp_path / "gate.jsonl", run_record=tmp_path / "runs.jsonl",
        fail_on_drift=fail_on_drift,
    )


def _mark(args, **fields):
    _r2_run_state.write_run_record(
        args.gate_marker,
        {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(), **fields},
    )


def _scan(args, covered):
    return _r2_drift_scan.scan_registry(args, NOW - timedelta(days=5), covered)[0]


def test_a_row_moved_into_the_first_positions_after_a_merge_is_still_scanned(tmp_path):
    old, new = _row("a", OLD_BODY, 4), _row("a", NEW_BODY, 3)
    other = _row("b", OLD_BODY, 4, n=2)
    covered = {_r2_drift_scan.row_id(old), _r2_drift_scan.row_id(other)}
    # The ungated row `new` sits at position 0 after the merge: a count of 2 would have skipped it.
    args = _args(tmp_path, [new, old, other])
    assert _scan(args, covered) == [("a", sha(OLD_BODY), sha(NEW_BODY))]


def test_a_reordered_registry_skips_exactly_the_covered_rows(tmp_path):
    old, new = _row("a", OLD_BODY, 4), _row("a", NEW_BODY, 3)
    covered = {_r2_drift_scan.row_id(old), _r2_drift_scan.row_id(new)}
    for order in ([old, new], [new, old]):
        assert _scan(_args(tmp_path, order), covered) == []
    only_old = {_r2_drift_scan.row_id(old)}
    assert len(_scan(_args(tmp_path, [new, old]), only_old)) == 1


def test_the_marker_round_trips_its_row_ids(tmp_path):
    rows = [_row("a", OLD_BODY, 4), _row("a", NEW_BODY, 3)]
    args = _args(tmp_path, rows)
    ids = sorted(_r2_drift_scan.row_id(r) for r in rows)
    _mark(args, gated_row_ids=ids)
    assert _r2_drift_scan.gated_row_ids(args) == set(ids)


def test_an_old_format_integer_marker_rescans_everything(tmp_path):
    old, new = _row("a", OLD_BODY, 4), _row("a", NEW_BODY, 3)
    args = _args(tmp_path, [old, new])
    _mark(args, gated_rows=2)
    covered = _r2_drift_scan.gated_row_ids(args)
    assert covered is None
    assert len(_scan(args, covered)) == 1


def test_a_missing_or_unreadable_marker_rescans_everything(tmp_path):
    args = _args(tmp_path, [])
    assert _r2_drift_scan.gated_row_ids(args) is None
    for bad in ("x", 3, [1, 2], None, True):
        _mark(args, gated_row_ids=bad)
        assert _r2_drift_scan.gated_row_ids(args) is None
    args.gate_marker.write_text("not json\n")
    assert _r2_drift_scan.gated_row_ids(args) is None


def test_a_passing_gate_writes_the_ids_of_every_registry_row(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    assert w.run(*flags) == 0
    last = json.loads((tmp_path / "drift-gate-passes.jsonl").read_text().splitlines()[-1])
    assert "gated_rows" not in last
    assert set(last["gated_row_ids"]) == {_r2_drift_scan.row_id(r) for r in w.registry_rows()}
