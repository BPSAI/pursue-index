"""An unresolved 2-digit-year date converges across polls.

The snapshot card's field is left EMPTY (never a 2-digit stored prior);
upstream's string stays in ``raw`` and a per-card marker in ``raw`` carries
the open item. The next poll over the same upstream value carries that item
instead of flagging it again, and the tranche still cannot take the
automatic path while it is open.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import tranche_diff  # noqa: E402
from _tranche_ready_run import normalized_manifest  # noqa: E402

from pursue_index.release import rates  # noqa: E402
from pursue_index.scrape.classify_tranche import (  # noqa: E402
    build_verdict_artifact,
    classify_tranche,
    render_verdict_summary,
)
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from pursue_index.scrape.poll_snapshot import generate_snapshot_diff  # noqa: E402
from pursue_index.scrape.year_resolve import TWO_DIGIT  # noqa: E402
from pursue_index.tranche_ready.record import RecordInputs, build_record  # noqa: E402
from pursue_index.tranche_ready.schema import load_schema, validate  # noqa: E402
from pursue_index.tranche_report import render_markdown  # noqa: E402

_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_U1 = "https://www.war.gov/medialink/case_0001.pdf"
_U2 = "https://www.war.gov/medialink/case_0002.pdf"
_MARKER = "_date_unresolved"


def _csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    body = "\r\n".join(f'{rel},"{title}",PDF,FBI,{inc},{url}' for rel, title, inc, url in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_PRIOR = _csv([("10/23/2026", "Case 1", "1/18/1957", _U1)])
_TRANCHE = _csv([("10/23/26", "Case 1", "1/18/57", _U1), ("10/23/26", "Case 2", "1/18/57", _U2)])


def _poll(tmp: Path, latest: Path, raw: bytes, n: int, overlay: Path | None = None):
    result = generate_snapshot_diff(raw, source_url=_URL, latest_path=latest,
                                    canonical_dir=tmp / f"c{n}", public_dir=tmp / f"p{n}",
                                    date_resolutions=overlay)
    old = json.loads(latest.read_text(encoding="utf-8"))
    overlay_rows = _load(overlay)
    manifest = json.loads(normalized_manifest(raw, _URL, old, overlay_rows)
                          .model_dump_json(by_alias=True))
    return result, manifest


def _load(overlay: Path | None):
    from pursue_index.scrape.date_resolutions import load_date_resolutions

    return load_date_resolutions(overlay) if overlay else {}


def _promote(tmp: Path, raw: bytes, n: int, latest: Path) -> dict:
    sha = build_manifest(raw, parse_csv(raw), _URL).csv_sha256
    snapshot = (tmp / f"c{n}" / f"{sha}.json").read_text(encoding="utf-8")
    latest.write_text(snapshot, encoding="utf-8")
    return json.loads(snapshot)


def _two_digit_dates(manifest: dict) -> list[str]:
    return [v for c in manifest["cards"] for v in (c["release_date"], c["incident_date"])
            if isinstance(v, str) and TWO_DIGIT.match(v)]


def _record(old: dict, diff: dict) -> dict:
    return build_record(RecordInputs(
        old_manifest=old, new_manifest={"csv_sha256": diff["tranche_sha256"], "cards": []},
        diff=diff, candidates=[], page_counts={}, new_fallback_ids=[], old_fetched=0,
        old_failures=[], judge=rates.JudgeRate(0.0165, rates.JUDGE_METERED),
        tranche_issue=None, supersedes=[], generated_by={"tool": "t", "version": "v"},
        generated_at="2026-11-20T00:00:00+00:00"))


def _setup(tmp_path: Path) -> Path:
    latest = tmp_path / "latest.json"
    save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _URL), latest)
    return latest


def test_two_polls_over_one_unresolved_row_flag_it_once(tmp_path: Path) -> None:
    latest = _setup(tmp_path)
    first, _ = _poll(tmp_path, latest, _TRANCHE, 1)
    assert [u["title"] for u in first.date_unresolved] == ["Case 2"]
    snap1 = _promote(tmp_path, _TRANCHE, 1, latest)
    card1 = snap1["cards"][1]
    assert card1["incident_date"] is None
    assert card1["raw"]["Incident Date"] == "1/18/57"
    marker = card1["raw"][_MARKER]
    assert marker == [{"field": "incident_date", "raw": "1/18/57",
                       "reason": "no_century_evidence",
                       "first_flagged_in": snap1["csv_sha256"],
                       "first_flagged_at": snap1["fetched_at"]}]
    assert _two_digit_dates(snap1) == []

    second, poll2 = _poll(tmp_path, latest, _TRANCHE, 2)
    assert second.date_unresolved == []
    assert [(o["card_id"], o["field"], o["raw"]) for o in second.date_open] == [
        (card1["card_id"], "incident_date", "1/18/57")]
    assert second.date_open[0]["first_flagged_in"] == snap1["csv_sha256"]
    assert second.field_changes == []
    assert second.date_report.passed_through == 0
    assert classify_tranche(second) == "needs-review"
    artifact = build_verdict_artifact(second, new_sha=snap1["csv_sha256"])
    assert "date_unresolved" not in artifact and len(artifact["date_open"]) == 1
    assert "still open" in render_verdict_summary(second)
    assert poll2["cards"][1]["incident_date"] is None
    assert poll2["cards"][1]["raw"][_MARKER] == marker
    assert _two_digit_dates(poll2) == []


def test_second_poll_receipt_and_record_still_stop(tmp_path: Path) -> None:
    latest = _setup(tmp_path)
    _poll(tmp_path, latest, _TRANCHE, 1)
    old = _promote(tmp_path, _TRANCHE, 1, latest)
    _, poll2 = _poll(tmp_path, latest, _TRANCHE, 2)
    diff = tranche_diff.diff_tranches(old, poll2, {}, fetch_byte_sha=lambda _u: None)
    assert "date_unresolved" not in diff and "date_unresolved" not in diff["summary"]
    assert diff["summary"]["date_open"] == 1
    assert diff["field_only_changes"] == []
    record = _record(old, diff)
    assert record["status"] == "stop-and-ask"
    assert any("still open" in r for r in record["stop_reasons"])
    assert validate(record, load_schema()) == []
    md = render_markdown(diff)
    assert "data/date_resolutions.json" in md and '"field": "incident_date"' in md


def test_manual_entry_resolves_and_becomes_the_prior(tmp_path: Path) -> None:
    latest = _setup(tmp_path)
    first, _ = _poll(tmp_path, latest, _TRANCHE, 1)
    cid = first.date_unresolved[0]["card_id"]
    _promote(tmp_path, _TRANCHE, 1, latest)
    overlay = tmp_path / "date_resolutions.json"
    overlay.write_text(json.dumps({"entries": [
        {"card_id": cid, "field": "incident_date", "value": "1/18/1957",
         "curator": "operator", "approved_at": "2026-11-20T12:00:00Z"}]}), encoding="utf-8")
    second, poll2 = _poll(tmp_path, latest, _TRANCHE, 2, overlay)
    assert second.date_unresolved == [] and second.date_open == []
    assert [(m["card_id"], m["value"], m["evidence"]) for m in second.date_report.manual_rows] == [
        (cid, "1/18/1957", "manual")]
    card = poll2["cards"][1]
    assert card["incident_date"] == "1/18/1957" and _MARKER not in card["raw"]
    assert classify_tranche(second) == "benign"
    latest.write_text(json.dumps(poll2), encoding="utf-8")  # promote poll 2
    third, poll3 = _poll(tmp_path, latest, _TRANCHE, 3)  # overlay no longer given
    assert third.date_unresolved == [] and third.date_open == []
    assert third.date_report.manual_rows == [] and third.field_changes == []
    assert poll3["cards"][1]["incident_date"] == "1/18/1957"


def test_changed_upstream_value_on_an_open_item_is_a_new_flag(tmp_path: Path) -> None:
    latest = _setup(tmp_path)
    _poll(tmp_path, latest, _TRANCHE, 1)
    _promote(tmp_path, _TRANCHE, 1, latest)
    changed = _csv([("10/23/26", "Case 1", "1/18/57", _U1), ("10/23/26", "Case 2", "1/19/57", _U2)])
    second, poll2 = _poll(tmp_path, latest, changed, 2)
    assert [(u["raw"], u["reason"]) for u in second.date_unresolved] == [
        ("1/19/57", "no_century_evidence")]
    assert second.date_open == []
    assert poll2["cards"][1]["raw"][_MARKER][0]["first_flagged_in"] == poll2["csv_sha256"]


def test_poll_cli_reads_the_overlay_for_snapshot_and_job(tmp_path: Path) -> None:
    import poll_snapshot
    from _tranche_ready_run import config_from_args

    latest = _setup(tmp_path)
    cid = json.loads(normalized_manifest(_TRANCHE, _URL, {"cards": []})
                     .model_dump_json())["cards"][1]["card_id"]
    overlay = tmp_path / "date_resolutions.json"
    overlay.write_text(json.dumps({"entries": [
        {"card_id": cid, "field": "incident_date", "value": "1/18/1957",
         "curator": "operator", "approved_at": "2026-11-20T12:00:00Z"}]}), encoding="utf-8")
    csv_path = tmp_path / "new.csv"
    csv_path.write_bytes(_TRANCHE)
    argv = ["--csv", str(csv_path), "--latest", str(latest), "--date-resolutions", str(overlay),
            "--canonical-dir", str(tmp_path / "c1"), "--public-dir", str(tmp_path / "p1"),
            "--diff-out", str(tmp_path / "diff.json")]
    assert poll_snapshot.main(argv) == 0
    [record] = tmp_path.glob("diff.r*.json")  # an applied entry names the variant
    artifact = json.loads(record.read_text())
    assert artifact["verdict"] == "needs-review"  # added
    assert "date_unresolved" not in artifact
    [snapshot] = (tmp_path / "c1").glob(f"{artifact['new_sha']}.r*.json")
    snap = json.loads(snapshot.read_text())
    assert snap["resolutions_digest"] == artifact["resolutions_digest"]
    assert snap["cards"][1]["incident_date"] == "1/18/1957"
    args = poll_snapshot._build_parser().parse_args([*argv, "--tranche-ready-dir", "x"])
    assert config_from_args(args).date_resolutions == overlay


def test_stored_prior_is_kept_unchanged_when_upstream_mismatches(tmp_path: Path) -> None:
    """A stored 4-digit prior is never emptied or overwritten: the row is
    flagged once, keeps the stored value, and converges on the next poll."""
    latest = _setup(tmp_path)
    tranche = _csv([("10/23/26", "Case 1", "1/18/58", _U1)])
    first, _ = _poll(tmp_path, latest, tranche, 1)
    assert [(u["raw"], u["reason"]) for u in first.date_unresolved] == [
        ("1/18/58", "prior_mismatch")]
    assert first.field_changes == []
    assert classify_tranche(first) == "needs-review"
    snap1 = _promote(tmp_path, tranche, 1, latest)
    card = snap1["cards"][0]
    assert card["incident_date"] == "1/18/1957"
    assert card["raw"]["Incident Date"] == "1/18/58"
    assert [m["reason"] for m in card["raw"][_MARKER]] == ["prior_mismatch"]

    second, poll2 = _poll(tmp_path, latest, tranche, 2)
    assert second.date_unresolved == []
    assert [(o["raw"], o["reason"]) for o in second.date_open] == [("1/18/58", "prior_mismatch")]
    assert second.field_changes == [] and classify_tranche(second) == "needs-review"
    assert poll2["cards"][0]["incident_date"] == "1/18/1957"
    assert poll2["cards"][0]["raw"][_MARKER] == card["raw"][_MARKER]
