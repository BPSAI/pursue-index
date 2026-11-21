"""Every snapshot resolver caller names the date-resolution overlay.

The resolver never infers the overlay from an arbitrary snapshots dir: a
caller passes the entries or the overlay file, or passes None and the dir
must be a checkout's ``data/manifests/snapshots`` (or its public mirror) --
any other dir is refused rather than read as "no overlay". The autopilot
turns a refusal into a clean precondition stop.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import typer

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402

from pursue_index.cli.ingest_promote import resolve_approved_snapshot  # noqa: E402
from pursue_index.ingest_run import locate_snapshot  # noqa: E402
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.date_resolutions import load_date_resolutions  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from pursue_index.scrape.variants import OverlayLocationError, VariantMismatchError  # noqa: E402
from tests.support.autopilot_fakes import (  # noqa: E402
    FakeRunner,
    make_checkout,
    receipt,
    run_engine,
)

_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_U = "https://www.war.gov/medialink/case_{:04d}.pdf"


def _csv(rows: list[tuple[str, str, str, int]]) -> bytes:
    body = "\r\n".join(f'{r},"{t}",PDF,FBI,{i},{_U.format(n)}' for r, t, i, n in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_PRIOR = _csv([("10/23/2026", "Case 1", "1/18/1957", 1)])
_NEW = _csv([("10/23/26", "Case 1", "1/18/57", 1), ("10/23/26", "Case 2", "1/18/57", 2)])
_SHA = build_manifest(_NEW, parse_csv(_NEW), _URL).csv_sha256
_ENTRY = {"card_id": parse_csv(_NEW)[1].card_id, "field": "incident_date",
          "value": "1/18/1957", "curator": "operator", "approved_at": "2026-11-20T12:00:00Z"}


def _poll(root: Path, overlay: Path) -> None:
    (root / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    latest = root / "data" / "manifests" / "latest.json"
    if not latest.exists():
        save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _URL), latest)
    (root / "new.csv").write_bytes(_NEW)
    assert poll_snapshot.main([
        "--csv", str(root / "new.csv"), "--latest", str(latest),
        "--date-resolutions", str(overlay),
        "--canonical-dir", str(root / "data" / "manifests" / "snapshots"),
        "--public-dir", str(root / "web" / "public" / "data" / "snapshots")]) == 0


@pytest.fixture()
def custom(tmp_path: Path) -> tuple[Path, Path]:
    """A non-standard snapshots dir holding the base and the variant, and
    the overlay file the variant was made with (outside any checkout)."""
    overlay = tmp_path / "elsewhere" / "resolutions.json"
    overlay.parent.mkdir()
    _poll(tmp_path / "src", overlay)  # base (overlay file absent)
    overlay.write_text(json.dumps({"entries": [_ENTRY]}), encoding="utf-8")
    _poll(tmp_path / "src", overlay)  # variant
    snaps = tmp_path / "custom-snaps"
    shutil.copytree(tmp_path / "src" / "data" / "manifests" / "snapshots", snaps)
    return snaps, overlay


def test_custom_dir_with_an_explicit_overlay_picks_the_variant(custom) -> None:
    snaps, overlay = custom
    variant = next(snaps.glob(f"{_SHA}.r*.json"))
    assert locate_snapshot(_SHA, snaps, overlay) == variant
    assert locate_snapshot(_SHA, snaps, load_date_resolutions(overlay)) == variant
    assert locate_snapshot(_SHA, snaps, {}) == snaps / f"{_SHA}.json"


def test_custom_dir_without_an_overlay_is_refused(custom) -> None:
    snaps, _ = custom
    with pytest.raises(OverlayLocationError, match="--date-resolutions"):
        locate_snapshot(_SHA, snaps, None)
    assert issubclass(OverlayLocationError, VariantMismatchError)
    assert locate_snapshot("f" * 64, snaps, None) is None  # nothing to resolve: no read


def test_public_mirror_layout_finds_the_checkouts_overlay(custom, tmp_path: Path) -> None:
    snaps, overlay = custom
    public = tmp_path / "repo" / "web" / "public" / "data" / "snapshots"
    shutil.copytree(snaps, public)
    (tmp_path / "repo" / "data").mkdir()
    shutil.copy(overlay, tmp_path / "repo" / "data" / "date_resolutions.json")
    assert locate_snapshot(_SHA, public, None) == next(public.glob(f"{_SHA}.r*.json"))


def test_ingest_run_refuses_a_custom_dir_without_date_resolutions(custom, tmp_path: Path) -> None:
    snaps, overlay = custom
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"tranche_sha256": _SHA}) + "\n")
    with pytest.raises(typer.Exit) as exc:
        resolve_approved_snapshot(_SHA, log, snaps, tmp_path / "diffs")
    assert exc.value.exit_code == 2
    assert resolve_approved_snapshot(_SHA, log, snaps, tmp_path / "diffs", overlay) == next(
        snaps.glob(f"{_SHA}.r*.json"))


def test_autopilot_stops_cleanly_when_no_snapshot_matches_the_overlay(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt(_SHA))
    save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _URL),
                  repo / "data" / "manifests" / "latest.json")
    _poll(repo, repo / "data" / "date_resolutions.json")  # base snapshot, no overlay yet
    (repo / "data" / "date_resolutions.json").write_text(
        json.dumps({"entries": [_ENTRY]}), encoding="utf-8")
    for args in (["add", "-A"], ["commit", "-q", "-m", "snapshot + overlay"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    code, doc = run_engine(tmp_path, repo, FakeRunner(repo, _SHA), sha=_SHA)
    assert code == 40
    assert doc["outcome"] == "precondition-missing"
    assert "regenerate" in doc["message"]
