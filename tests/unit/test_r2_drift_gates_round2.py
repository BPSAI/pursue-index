"""Verify-gates round 2, drift side: the gate marker's covered rows, and the file-type change warning."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


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


# (The marker's covered rows are keyed by stable id: see test_r2_gate_row_ids.py.)


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
