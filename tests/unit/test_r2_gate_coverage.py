"""A row is marked gated only by the scan that evaluated it; skipped rows stay ungated."""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _r2_drift_scan as ds  # noqa: E402

NOW = datetime.now(UTC)
SINCE = NOW - timedelta(days=5)


def _row(card, n, days_ago, tag="x"):
    when = "garbage" if days_ago is None else (NOW - timedelta(days=days_ago)).isoformat()
    return {
        "card_id": card, "asset_url": f"https://www.war.gov/medialink/ufo/{card}.pdf",
        "asset_filename": f"{card}.pdf", "byte_sha256": f"{n:064x}", "byte_size": n,
        "fetched_at": when, "tag": tag,
    }


def _args(tmp_path, rows):
    reg = tmp_path / "registry.jsonl"
    reg.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return SimpleNamespace(registry=reg, fail_on_drift=True)


def _marker(args, gated):
    """What ``main`` would write: the carried-forward ids plus this run's covered ids."""
    return set(ds.scan_registry(args, SINCE, gated)[1])


def test_a_late_merged_row_with_an_old_fetched_at_is_not_marked_gated(tmp_path, capsys):
    fresh, late = _row("a", 1, 1), _row("a", 2, 30, tag="late")
    args = _args(tmp_path, [fresh, late])  # the late-merged row sits after the fresh one
    marker = _marker(args, None)
    assert ds.row_id(late) not in marker
    assert ds.row_id(fresh) in marker
    assert "1 outside the window" in capsys.readouterr().out


def test_an_unparseable_time_is_not_marked_and_is_reported(tmp_path, capsys):
    good, bad = _row("a", 1, 1), _row("b", 2, None)
    marker = _marker(_args(tmp_path, [good, bad]), None)
    assert marker == {ds.row_id(good)}
    out = capsys.readouterr().out
    assert "1 registry rows left ungated" in out and "1 unparseable time (e.g. b)" in out


def test_a_scan_that_skips_nothing_prints_no_ungated_line(tmp_path, capsys):
    _marker(_args(tmp_path, [_row("a", 1, 1)]), None)
    assert "ungated" not in capsys.readouterr().out


def test_the_choke_point_is_the_only_source_of_covered_ids(tmp_path):
    rows = [_row("a", 1, 30), _row("a", 2, 1), _row("b", 3, None)]
    drift, covered, skipped = ds.drift_and_coverage({"a": rows[:2], "b": rows[2:]}, SINCE)
    assert drift == [("a", f"{1:064x}", f"{2:064x}")]
    assert covered == {ds.row_id(rows[1])}
    assert set(skipped) == {ds.row_id(rows[0]), ds.row_id(rows[2])}


def test_a_gated_row_stays_covered_only_while_it_is_in_the_registry(tmp_path):
    kept, gone = _row("a", 1, 40), _row("b", 2, 40)
    args = _args(tmp_path, [kept])
    marker = _marker(args, {ds.row_id(kept), ds.row_id(gone)})
    assert marker == {ds.row_id(kept)}


@pytest.mark.parametrize("seed", range(40))
def test_no_skipped_row_is_ever_marked_and_every_scanned_row_is(tmp_path, seed):
    rng = random.Random(seed)
    rows, scanned, skipped, gated = [], set(), set(), set()
    for k in range(rng.randint(3, 12)):
        card = f"c{k % 4}"
        kind = rng.choice(["in", "old", "bad", "gated"])
        r = _row(card, k + 1, {"in": rng.uniform(0, 4), "old": rng.uniform(6, 60), "bad": None,
                               "gated": rng.choice([1, 30, None])}[kind], tag=str(k))
        rows.append(r)
        rid = ds.row_id(r)
        {"in": scanned, "old": skipped, "bad": skipped, "gated": gated}[kind].add(rid)
    rng.shuffle(rows)  # late merges and reorders: position carries no meaning
    marker = _marker(_args(tmp_path, rows), gated or None)
    assert not (marker & skipped)
    assert scanned <= marker
    assert gated <= marker  # earlier coverage carries forward
    assert marker == scanned | gated


def test_an_old_format_or_missing_marker_rescans_the_window(tmp_path):
    rows = [_row("a", 1, 3), _row("a", 2, 1)]
    args = _args(tmp_path, rows)
    args.gate_marker = tmp_path / "gate.jsonl"
    assert ds.gated_row_ids(args) is None  # missing
    args.gate_marker.write_text(json.dumps(
        {"schema": 1, "completed_at": (NOW - timedelta(days=1)).isoformat(), "gated_rows": 2}) + "\n")
    assert ds.gated_row_ids(args) is None  # old integer format
    assert len(ds.scan_registry(args, SINCE, None)[0]) == 1
