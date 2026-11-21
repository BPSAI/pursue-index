"""An acknowledged-unknown date across polls, receipts and records.

The entry clears the stop an UNRESOLVED date forces -- the verdict, the
receipt and the tranche-ready record -- without writing any date, stays
acknowledged on later polls over the same upstream value, and re-opens as a
fresh flag when upstream's value changes. Acknowledged entries are part of
the overlay digest, so the snapshot is a ``.r<digest12>`` variant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tranche_diff  # noqa: E402

from pursue_index.release import rates  # noqa: E402
from pursue_index.scrape.classify_tranche import (  # noqa: E402
    build_verdict_artifact,
    classify_tranche,
    render_verdict_summary,
)
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.date_resolutions import load_date_resolutions  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from pursue_index.scrape.poll_snapshot import generate_snapshot_diff  # noqa: E402
from pursue_index.scrape.variants import overlay_digest, resolve_snapshot  # noqa: E402
from pursue_index.tranche_ready.record import RecordInputs, build_record  # noqa: E402
from pursue_index.tranche_ready.schema import load_schema, validate  # noqa: E402
from pursue_index.tranche_report import render_markdown  # noqa: E402

_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_U1 = "https://www.war.gov/medialink/case_0001.pdf"
_U2 = "https://www.war.gov/medialink/case_0002.pdf"
_A = "_date_acknowledged"
_M = "_date_unresolved"


def _csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    body = "\r\n".join(f'{rel},"{title}",PDF,FBI,{inc},{url}' for rel, title, inc, url in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_PRIOR = _csv([("10/23/2026", "Case 1", "1/18/1957", _U1), ("10/23/2026", "Case 2", "", _U2)])
_TRANCHE = _csv([("10/23/26", "Case 1", "1/18/57", _U1), ("10/23/26", "Case 2", "7/15/05", _U2)])
_CHANGED = _csv([("10/23/26", "Case 1", "1/18/57", _U1), ("10/23/26", "Case 2", "7/16/05", _U2)])


def _setup(tmp: Path) -> tuple[Path, str]:
    latest = tmp / "latest.json"
    manifest = build_manifest(_PRIOR, parse_csv(_PRIOR), _URL)
    save_manifest(manifest, latest)
    return latest, manifest.cards[1].card_id


def _overlay(tmp: Path, card_id: str) -> Path:
    path = tmp / "date_resolutions.json"
    path.write_text(json.dumps({"entries": [{
        "card_id": card_id, "field": "incident_date", "value": None,
        "status": "acknowledged-unknown", "reason": "upstream year conflicts with the title",
        "curator": "<who>", "approved_at": "2026-11-21T00:00:00Z",
        "upstream_value": "7/15/05"}]}), encoding="utf-8")
    return path


def _poll(tmp: Path, latest: Path, raw: bytes, n: int, overlay: Path | None):
    return generate_snapshot_diff(raw, source_url=_URL, latest_path=latest,
                                  canonical_dir=tmp / f"c{n}", public_dir=tmp / f"p{n}",
                                  date_resolutions=overlay)


def _snapshot(tmp: Path, n: int, raw: bytes = _TRANCHE) -> dict:
    sha = build_manifest(raw, parse_csv(raw), _URL).csv_sha256
    [path] = (tmp / f"c{n}").glob(f"{sha}*.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _record(old: dict, diff: dict) -> dict:
    return build_record(RecordInputs(
        old_manifest=old, new_manifest={"csv_sha256": diff["tranche_sha256"], "cards": []},
        diff=diff, candidates=[], page_counts={}, new_fallback_ids=[], old_fetched=0,
        old_failures=[], judge=rates.JudgeRate(0.0165, rates.JUDGE_METERED),
        tranche_issue=None, supersedes=[], generated_by={"tool": "t", "version": "v"},
        generated_at="2026-11-21T00:00:00+00:00"))


def test_acknowledged_entry_clears_the_verdict(tmp_path: Path) -> None:
    latest, cid = _setup(tmp_path)
    result = _poll(tmp_path, latest, _TRANCHE, 1, _overlay(tmp_path, cid))
    assert result.date_unresolved == [] and result.date_open == []
    acked = result.date_report.acknowledged
    assert [(a["card_id"], a["raw"]) for a in acked] == [(cid, "7/15/05")]
    assert classify_tranche(result) == "benign"
    artifact = build_verdict_artifact(result, new_sha="s")
    assert artifact["verdict"] == "benign" and len(artifact["date_acknowledged"]) == 1
    assert "date_unresolved" not in artifact
    assert "acknowledged unknown: 1" in render_verdict_summary(result)
    card = _snapshot(tmp_path, 1)["cards"][1]
    assert card["incident_date"] is None and _M not in card["raw"]
    assert card["raw"][_A][0]["raw"] == "7/15/05"


def test_two_polls_stay_acknowledged(tmp_path: Path) -> None:
    latest, cid = _setup(tmp_path)
    overlay = _overlay(tmp_path, cid)
    _poll(tmp_path, latest, _TRANCHE, 1, overlay)
    latest.write_text(json.dumps(_snapshot(tmp_path, 1)), encoding="utf-8")
    second = _poll(tmp_path, latest, _TRANCHE, 2, overlay)
    assert second.date_unresolved == [] and second.date_open == []
    assert len(second.date_report.acknowledged) == 1 and second.field_changes == []
    assert classify_tranche(second) == "benign"
    assert _snapshot(tmp_path, 2)["cards"][1]["incident_date"] is None


def test_upstream_change_reopens_and_stops(tmp_path: Path) -> None:
    latest, cid = _setup(tmp_path)
    overlay = _overlay(tmp_path, cid)
    _poll(tmp_path, latest, _TRANCHE, 1, overlay)
    old = _snapshot(tmp_path, 1)
    latest.write_text(json.dumps(old), encoding="utf-8")
    second = _poll(tmp_path, latest, _CHANGED, 2, overlay)
    assert second.date_report.acknowledged == []
    assert [(u["raw"], u["reason"]) for u in second.date_unresolved] == [
        ("7/16/05", "acknowledged_value_changed")]
    assert classify_tranche(second) == "needs-review"
    new = _snapshot(tmp_path, 2, _CHANGED)
    diff = tranche_diff.diff_tranches(old, new, {}, fetch_byte_sha=lambda _u: None,
                                      date_overlay=load_date_resolutions(overlay))
    assert _record(old, diff)["status"] == "stop-and-ask"
    md = render_markdown(diff)  # the worklist offers both kinds of entry
    assert '"value": "7/16/YYYY"' in md and '"status": "acknowledged-unknown"' in md
    assert '"upstream_value": "7/16/05"' in md


def test_receipt_and_record_with_an_acknowledged_row(tmp_path: Path) -> None:
    latest, cid = _setup(tmp_path)
    overlay = _overlay(tmp_path, cid)
    old = json.loads(latest.read_text(encoding="utf-8"))
    _poll(tmp_path, latest, _TRANCHE, 1, overlay)
    diff = tranche_diff.diff_tranches(old, _snapshot(tmp_path, 1), {},
                                      fetch_byte_sha=lambda _u: None,
                                      date_overlay=load_date_resolutions(overlay))
    assert diff["summary"]["date_acknowledged"] == 1
    assert "date_unresolved" not in diff and "date_open" not in diff
    assert diff["date_acknowledged"][0]["curator"] == "<who>"
    record = _record(old, diff)
    assert record["status"] == "ready" and "stop_reasons" not in record
    assert validate(record, load_schema()) == []
    md = render_markdown(diff)
    assert "## Date acknowledged unknown" in md and "dates acknowledged unknown" in md


def test_digest_changes_and_the_variant_is_resolved(tmp_path: Path) -> None:
    latest, cid = _setup(tmp_path)
    overlay = _overlay(tmp_path, cid)
    result = _poll(tmp_path, latest, _TRANCHE, 1, overlay)
    cards = [c.model_dump(mode="json") for c in parse_csv(_TRANCHE)]
    assert overlay_digest(load_date_resolutions(overlay), cards) == result.resolutions_digest
    assert result.resolutions_digest is not None and overlay_digest({}, cards) is None
    sha = build_manifest(_TRANCHE, parse_csv(_TRANCHE), _URL).csv_sha256
    picked = resolve_snapshot(sha, tmp_path / "c1", overlay)
    assert picked.name == f"{sha}.r{result.resolutions_digest[:12]}.json"
