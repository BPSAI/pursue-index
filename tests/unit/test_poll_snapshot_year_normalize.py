"""``generate_snapshot_diff`` restores 4-digit years before it diffs and
writes the snapshot (tranche bae7455d)."""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.scrape.classify_tranche import build_verdict_artifact, render_verdict_summary
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.poll_snapshot import generate_snapshot_diff

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_URL1 = "https://www.war.gov/medialink/case_0001.pdf"
_URL2 = "https://www.war.gov/medialink/case_0002.pdf"


def _csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    body = "\r\n".join(f'{rel},"{title}",PDF,FBI,{inc},{url}' for rel, title, inc, url in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


def _run(tmp_path: Path, prior: bytes, new: bytes):
    latest = tmp_path / "latest.json"
    save_manifest(build_manifest(prior, parse_csv(prior), _SOURCE_URL), latest)
    result = generate_snapshot_diff(new, source_url=_SOURCE_URL, latest_path=latest,
                                    canonical_dir=tmp_path / "c", public_dir=tmp_path / "p")
    sha = build_manifest(new, parse_csv(new), _SOURCE_URL).csv_sha256
    snapshot = json.loads((tmp_path / "c" / f"{sha}.json").read_text(encoding="utf-8"))
    return result, snapshot, sha


def test_existing_rows_restored_so_no_field_changes(tmp_path: Path) -> None:
    prior = _csv([("10/23/2026", "Case 1", "1/18/1957", _URL1)])
    new = _csv([("10/23/26", "Case 1", "1/18/57", _URL1)])
    result, snapshot, _ = _run(tmp_path, prior, new)
    assert result.field_changes == []
    assert result.date_unresolved == []
    card = snapshot["cards"][0]
    assert (card["release_date"], card["incident_date"]) == ("10/23/2026", "1/18/1957")
    assert card["raw"] == {"Release Date": "10/23/26", "Incident Date": "1/18/57"}


def test_new_row_without_evidence_is_flagged_and_left_as_given(tmp_path: Path) -> None:
    prior = _csv([("10/23/2026", "Case 1", "1/18/1957", _URL1)])
    new = _csv([("10/23/26", "Case 1", "1/18/57", _URL1), ("", "Case 2", "1/18/57", _URL2)])
    result, snapshot, _ = _run(tmp_path, prior, new)
    added = result.added[0]
    assert added.incident_date == "1/18/57"
    assert result.date_unresolved == [{"card_id": added.card_id, "title": "Case 2",
                                       "field": "incident_date", "raw": "1/18/57",
                                       "reason": "no_century_evidence"}]
    assert snapshot["cards"][1]["incident_date"] == "1/18/57"


def test_unresolved_rows_reach_the_verdict_artifact_and_summary(tmp_path: Path) -> None:
    prior = _csv([("10/23/2026", "Case 1", "1/18/1957", _URL1)])
    new = _csv([("10/23/26", "Case 1", "1/18/57", _URL1), ("", "Case 2", "1/18/57", _URL2)])
    result, _, sha = _run(tmp_path, prior, new)
    artifact = build_verdict_artifact(result, new_sha=sha)
    assert artifact["date_unresolved"] == result.date_unresolved
    summary = render_verdict_summary(result)
    assert "date_unresolved: 1" in summary
    assert (f"`{result.added[0].card_id}` Case 2 — incident_date `1/18/57` "
            "(no_century_evidence)") in summary
    assert "* 2-digit priors passed through: 0" in summary


def test_new_release_date_resolves_by_release_window(tmp_path: Path) -> None:
    prior = _csv([("10/23/2026", "Case 1", "1/18/1957", _URL1)])
    new = _csv([("10/23/26", "Case 1", "1/18/57", _URL1), ("11/20/26", "Case 2", "", _URL2)])
    result, snapshot, _ = _run(tmp_path, prior, new)
    assert snapshot["cards"][1]["release_date"] == "11/20/2026"
    assert result.date_unresolved == []
    assert [r["evidence"] for r in result.date_report.window_rows] == ["release-window"]
    assert "release window 2026-" in render_verdict_summary(result)


def test_artifact_omits_date_unresolved_when_none(tmp_path: Path) -> None:
    prior = _csv([("10/23/2026", "Case 1", "1/18/1957", _URL1)])
    result, _, sha = _run(tmp_path, prior, _csv([("10/23/26", "Case 1", "1/18/57", _URL1)]))
    assert "date_unresolved" not in build_verdict_artifact(result, new_sha=sha)
    assert "date_unresolved" not in render_verdict_summary(result)
