"""Verify-gates round 2, drift side: the gate marker's covered rows, and the file-type change warning."""

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

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha, url  # noqa: E402

# --- 5. the drift window skips rows the last passing gate covered ------------------------


def _row(cid, body, when, u=None, **kw):
    return {
        "card_id": cid, "asset_url": u or url(1), "asset_filename": "c.pdf", "byte_sha256": sha(body),
        "byte_size": len(body), "fetched_at": when.isoformat(), **kw,
    }


NOW = datetime.now(UTC)


def test_registry_drift_since_skips_the_gated_rows():
    rows = [_row("c1", OLD_BODY, NOW - timedelta(days=2)), _row("c1", NEW_BODY, NOW - timedelta(days=1))]
    registry = {"c1": rows}
    since = NOW - timedelta(days=3)
    assert r2.registry_drift_since(registry, since) == [("c1", sha(OLD_BODY), sha(NEW_BODY))]
    assert r2.registry_drift_since(registry, since, rows_after=[]) == []
    assert r2.registry_drift_since(registry, since, rows_after=rows[1:]) != []


def test_the_marker_carries_the_gated_row_count_and_the_next_gate_starts_after_it(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    marker = tmp_path / "drift-gate-passes.jsonl"
    assert w.run(*flags) == 1, "undisposed drift fails the first gate"
    assert not marker.exists()
    # Suppose a later gate passed (the drift was dispositioned) having covered every row.
    w.rows = w.registry_rows()
    args = SimpleNamespace(registry=w.registry, gate_marker=marker, run_record=w.record)
    _r2_run_state.write_run_record(
        marker,
        {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
         "gated_rows": len(w.rows)},
    )
    assert _r2_drift_scan.gated_row_count(args) == len(w.rows)
    # The drift row is behind the marker's count: the next gate does not rescan it, and its own marker says so.
    assert w.run(*flags) == 0
    last = json.loads(marker.read_text().splitlines()[-1])
    assert last["gated_rows"] == len(w.registry_rows())


def test_a_new_row_after_the_gated_count_is_still_scanned(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    marker = tmp_path / "drift-gate-passes.jsonl"
    _r2_run_state.write_run_record(
        marker, {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
                 "gated_rows": len(w.rows)}
    )
    assert w.run(*flags) == 1, "the row this run appended is past the gated count and is drift"


def test_a_missing_or_old_format_marker_falls_back_to_the_whole_window(tmp_path):
    args = SimpleNamespace(registry=tmp_path / "r.jsonl", gate_marker=tmp_path / "m.jsonl", run_record=tmp_path / "x")
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat()})
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat(), "gated_rows": "x"})
    assert _r2_drift_scan.gated_row_count(args) is None
    _r2_run_state.write_run_record(args.gate_marker, {"completed_at": NOW.isoformat(), "gated_rows": -3})
    assert _r2_drift_scan.gated_row_count(args) is None


def test_a_registry_shorter_than_the_gated_count_is_scanned_whole(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    _r2_run_state.write_run_record(
        tmp_path / "drift-gate-passes.jsonl",
        {"schema": _r2_run_state.GATE_MARKER_SCHEMA, "completed_at": (NOW - timedelta(days=2)).isoformat(),
         "gated_rows": 10_000},
    )
    assert w.run(*flags) == 1


# --- 7. a file-type change is a warning ----------------------------------------------------


def test_a_changed_url_and_file_type_prints_a_type_change_warning(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=NEW_BODY, head_matches_prior=False)
    old_url = w.cards[0]["asset_url"]
    new_url = "https://www.war.gov/medialink/ufo/c1.mp4"
    w.cards[0].update(asset_url=new_url, asset_filename="c1.mp4", asset_type="VID")
    w.bodies[new_url] = NEW_BODY
    flags = ["--fail-on-drift", "--dispositions", str(w.dispositions), "--run-record", str(w.record)]
    assert w.run(*flags) == 0, "net-new under the per-asset rule: a warning, not drift"
    out = capsys.readouterr().out
    assert f"[r2-archive] TYPE CHANGE: {cid} pdf -> mp4 (www.war.gov -> www.war.gov)" in out
    assert old_url not in out


def test_a_same_type_move_is_not_warned(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    new_url = "https://www.war.gov/elsewhere/c1.pdf"
    w.cards[0]["asset_url"] = new_url
    w.bodies[new_url] = OLD_BODY
    w.run()
    assert "TYPE CHANGE" not in capsys.readouterr().out


def test_a_second_asset_of_another_type_is_not_a_type_change(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    cid = w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    extra = "https://www.war.gov/medialink/ufo/c1.mp4"
    w.cards.append({**w.cards[0], "asset_url": extra, "asset_filename": "c1.mp4", "asset_type": "VID"})
    w.bodies[extra] = NEW_BODY
    w.run()
    assert "TYPE CHANGE" not in capsys.readouterr().out and cid


def test_the_scan_side_emits_the_same_warning_and_no_drift(capsys):
    old, new = _row("c1", OLD_BODY, NOW - timedelta(days=3)), _row(
        "c1", NEW_BODY, NOW - timedelta(days=1), u="https://cdn.example.com/c1.mp4", asset_filename="c1.mp4"
    )
    assert r2.registry_drift_since({"c1": [old, new]}, NOW - timedelta(days=2)) == []
    assert "[r2-archive] TYPE CHANGE: c1 pdf -> mp4 (www.war.gov -> cdn.example.com)" in capsys.readouterr().out


def test_the_scan_side_is_quiet_for_rows_before_the_window(capsys):
    old, new = _row("c1", OLD_BODY, NOW - timedelta(days=9)), _row(
        "c1", NEW_BODY, NOW - timedelta(days=8), u="https://www.war.gov/c1.mp4", asset_filename="c1.mp4"
    )
    r2.registry_drift_since({"c1": [old, new]}, NOW - timedelta(days=2))
    assert "TYPE CHANGE" not in capsys.readouterr().out
