"""Verify-gates round 3: the weekly full-hash run drift-checks every ungated row, old or not."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_drift_scan as ds  # noqa: E402

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, card_id, sha, url  # noqa: E402

NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=5)


def _row(card, body, days_ago, **kw):
    return {
        "card_id": card, "asset_url": f"https://www.war.gov/medialink/ufo/{card}.pdf",
        "asset_filename": f"{card}.pdf", "byte_sha256": sha(body), "byte_size": len(body),
        "fetched_at": (NOW - timedelta(days=days_ago)).isoformat(), **kw,
    }


def test_the_sweep_compares_a_row_outside_the_window_and_marks_it_after_the_comparison():
    early, late = _row("a", OLD_BODY, 40), _row("a", NEW_BODY, 30)
    registry = {"a": [early, late]}
    drift, covered, skipped = ds.drift_and_coverage(registry, SINCE, sweep=True)
    assert drift == [("a", sha(OLD_BODY), sha(NEW_BODY))]
    assert covered == {ds.row_id(early), ds.row_id(late)} and skipped == {}


def test_without_the_sweep_the_same_rows_stay_ungated_and_unchecked():
    early, late = _row("a", OLD_BODY, 40), _row("a", NEW_BODY, 30)
    drift, covered, skipped = ds.drift_and_coverage({"a": [early, late]}, SINCE)
    assert drift == [] and covered == set()
    assert set(skipped) == {ds.row_id(early), ds.row_id(late)}


def test_the_sweep_also_checks_a_row_with_an_unparseable_time():
    early, bad = _row("a", OLD_BODY, 40), _row("a", NEW_BODY, 1, fetched_at="garbage")
    drift, covered, _ = ds.drift_and_coverage({"a": [early, bad]}, SINCE, sweep=True)
    assert drift == [("a", sha(OLD_BODY), sha(NEW_BODY))] and ds.row_id(bad) in covered


def test_the_sweep_skips_rows_an_earlier_gate_already_covered(tmp_path):
    early, late = _row("a", OLD_BODY, 40), _row("a", NEW_BODY, 30)
    reg = tmp_path / "registry.jsonl"
    reg.write_text("".join(json.dumps(r) + "\n" for r in (early, late)))
    args = SimpleNamespace(registry=reg, fail_on_drift=True, full_hash=True)
    drift, ids = ds.scan_registry(args, SINCE, {ds.row_id(late)})
    assert drift == [] and set(ids) == {ds.row_id(early), ds.row_id(late)}


def test_an_old_type_change_is_not_warned_about_by_the_sweep(capsys):
    old = _row("a", OLD_BODY, 40)
    new = _row("a", NEW_BODY, 30, asset_url="https://www.war.gov/c.mp4", asset_filename="c.mp4")
    ds.drift_and_coverage({"a": [old, new]}, SINCE, sweep=True)
    assert "TYPE CHANGE" not in capsys.readouterr().out


# --- end to end: the weekly run, then the daily -----------------------------------------------


def _late_merged(w: World) -> tuple[str, list[dict]]:
    """A card that is not in the manifest, with two long-dated rows whose bytes differ."""
    cid = card_id(9)
    rows = [
        {"card_id": cid, "asset_url": url(9), "asset_filename": "c9.pdf", "byte_sha256": sha(b),
         "byte_size": len(b), "fetched_at": f"2026-05-1{i}T00:00:00+00:00"}
        for i, b in enumerate((OLD_BODY, NEW_BODY))
    ]
    w.rows.extend(rows)
    return cid, rows


def _marker(w: World) -> set[str]:
    path = w.registry.parent / "drift-gate-passes.jsonl"
    if not path.exists():
        return set()
    return set(json.loads(path.read_text().splitlines()[-1])["gated_row_ids"])


def _weekly(w, *extra):
    return w.run(
        "--full-hash", "--max-bytes-per-run", "1000000", "--fail-on-drift",
        "--dispositions", str(w.dispositions), "--run-record", str(w.record), *extra,
    )


def test_the_weekly_run_fails_on_a_late_merged_drifted_row_then_passes_once_dispositioned(
    tmp_path, monkeypatch, capsys
):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    cid, rows = _late_merged(w)
    assert _weekly(w) == 1
    assert "BYTE DRIFT" in capsys.readouterr().err and _marker(w) == set()
    w.dispositions.write_text(json.dumps({
        "card_id": cid, "old_sha256": sha(OLD_BODY), "new_sha256": sha(NEW_BODY),
        "disposition": "resave-content-verified", "reviewed_at": "2026-11-21",
        "evidence": "re-save, same content", "evidence_ref": "3" * 64, "ocr_from": sha(OLD_BODY),
    }) + "\n")
    assert _weekly(w) == 0
    assert {ds.row_id(r) for r in rows} <= _marker(w)


def test_the_daily_still_leaves_the_late_row_ungated_and_reports_it(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)
    _, rows = _late_merged(w)
    assert w.run("--fail-on-drift", "--dispositions", str(w.dispositions)) == 0
    assert "3 outside the window" in capsys.readouterr().out  # the two late rows and the card's prior row
    assert not ({ds.row_id(r) for r in rows} & _marker(w))
