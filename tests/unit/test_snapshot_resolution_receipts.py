"""The receipt and the tranche-ready record follow the snapshot's identity.

With an applicable date-resolution entry, ``poll_snapshot.py
--tranche-ready-dir`` writes ``tranche-diff-<sha12>.r<digest12>.{json,md}``
and ``<sha12>.r<digest12>.json`` next to (never over) the base files; every
reader -- approve, run, the autopilot, ``tranche_diff.py`` -- finds the
variant for the current overlay.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.date_resolutions import load_date_resolutions
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.variants import current_digest
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402
import tranche_diff  # noqa: E402

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_URL = "https://www.war.gov/medialink/case_{:04d}.pdf"


def _csv(rows: list[tuple[int, str, str]]) -> bytes:
    body = [f'{rel},"DOW-UAP-D{n:03d}, Case",PDF,FBI,{inc},{_URL.format(n)}'
            for n, rel, inc in rows]
    return ("﻿" + _HEADER + "\r\n" + "\r\n".join(body) + "\r\n").encode("utf-8")


_PRIOR = _csv([(1, "5/8/2026", "1/15/1995")])
_NEW = _csv([(1, "5/8/26", "1/15/95"), (2, "5/8/26", "1/18/57")])
_SHA = build_manifest(_NEW, parse_csv(_NEW), _SOURCE_URL).csv_sha256
_CASE2 = parse_csv(_NEW)[1].card_id


@pytest.fixture()
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "manifests").mkdir(parents=True)
    save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _SOURCE_URL),
                  tmp_path / "data" / "manifests" / "latest.json")
    (tmp_path / "new.csv").write_bytes(_NEW)
    monkeypatch.setattr(csv_fetcher, "http_get",
                        FakeHttpGet(bodies={_URL.format(2): pdf_bytes(2)}))
    return tmp_path


def _run(root: Path) -> int:
    data = root / "data"
    return poll_snapshot.main([
        "--csv", str(root / "new.csv"), "--latest", str(data / "manifests" / "latest.json"),
        "--source-url", _SOURCE_URL, "--date-resolutions", str(data / "date_resolutions.json"),
        "--canonical-dir", str(data / "manifests" / "snapshots"),
        "--public-dir", str(root / "web" / "public" / "data" / "snapshots"),
        "--diff-out", str(data / "manifests" / "diffs" / f"{_SHA}.json"),
        "--qc-bundle", str(root / "absent.json"),
        "--tranche-ready-dir", str(data / "tranche-ready"),
        "--tranche-diff-dir", str(data / "tranche-diffs"),
        "--registry", str(root / "absent-registry.jsonl"),
        "--poll-state", str(root / "absent-state.json"), "--csv-archive", str(root / "csv"),
        "--error-out", str(root / "error.md"),
    ])


def _resolve(root: Path, who: str = "operator") -> str:
    path = root / "data" / "date_resolutions.json"
    path.write_text(json.dumps({"entries": [
        {"card_id": _CASE2, "field": "incident_date", "value": "1/18/1957", "curator": who,
         "approved_at": "2026-11-20T12:00:00Z"}]}), encoding="utf-8")
    digest = current_digest(_SHA, root / "data" / "manifests" / "snapshots",
                            load_date_resolutions(path))
    return f".r{digest[:12]}"


def _outputs(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for sub in ("data/tranche-diffs", "data/tranche-ready", "data/manifests")
            for p in sorted((root / sub).rglob("*")) if p.is_file()}


def test_receipt_and_record_take_the_variant_name(root: Path) -> None:
    assert _run(root) == 0
    sha12 = _SHA[:12]
    base = _outputs(root)
    assert json.loads(base[f"data/tranche-diffs/tranche-diff-{sha12}.json"])["date_unresolved"]
    suffix = _resolve(root)
    assert _run(root) == 0
    after = _outputs(root)
    assert {k: v for k, v in after.items() if k in base and "index.json" not in k} == {
        k: v for k, v in base.items() if "index.json" not in k}  # nothing rewritten
    receipt = json.loads(after[f"data/tranche-diffs/tranche-diff-{sha12}{suffix}.json"])
    assert "date_unresolved" not in receipt
    assert [m["card_id"] for m in receipt["date_manual_rows"]] == [_CASE2]
    assert f"data/tranche-diffs/tranche-diff-{sha12}{suffix}.md" in after
    record = json.loads(after[f"data/tranche-ready/{sha12}{suffix}.json"])
    assert not any("date_unresolved" in r for r in record.get("stop_reasons", []))
    assert _run(root) == 0
    assert _outputs(root) == after  # the same overlay again is a no-op


def test_readers_find_the_variant_for_the_current_overlay(root: Path) -> None:
    from pursue_index.cli.ingest_cli import _find_diff_artifact
    from pursue_index.tranche_autopilot.engine import receipt_path

    diffs, snaps = root / "data" / "tranche-diffs", root / "data" / "manifests" / "snapshots"
    assert _run(root) == 0
    assert _find_diff_artifact(_SHA, diffs, snaps) == diffs / f"tranche-diff-{_SHA[:12]}.json"
    suffix = _resolve(root)
    assert _run(root) == 0
    want = diffs / f"tranche-diff-{_SHA[:12]}{suffix}.json"
    assert _find_diff_artifact(_SHA, diffs, snaps) == want
    assert receipt_path(root, _SHA) == want


def test_tranche_diff_script_names_its_outputs_by_the_variant(
        root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(root) == 0
    suffix = _resolve(root)
    assert _run(root) == 0
    snapshot = root / "data" / "manifests" / "snapshots" / f"{_SHA}{suffix}.json"
    (root / "registry.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(tranche_diff, "_fetch_byte_sha_via_curl", lambda _url: None)
    monkeypatch.setattr(sys, "argv", [
        "tranche_diff.py", "--old-manifest", str(root / "data" / "manifests" / "latest.json"),
        "--new-manifest", str(snapshot), "--registry", str(root / "registry.jsonl"),
        "--date-resolutions", str(root / "data" / "date_resolutions.json"),
        "--out-dir", str(root / "out")])
    assert tranche_diff.main() == 0
    assert sorted(p.name for p in (root / "out").iterdir()) == [
        f"tranche-diff-{_SHA[:12]}{suffix}.json", f"tranche-diff-{_SHA[:12]}{suffix}.md"]
