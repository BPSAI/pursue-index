"""Both snapshot ``index.json`` files list exactly one entry per csv_sha256.

When a ``.r<digest12>`` variant of a snapshot is written (or promoted), it
REPLACES that sha's entry, carrying its ``resolutions_digest``; the /diff
page, keyed by sha, never sees the superseded file. With no variant on disk
both index files keep their bytes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_snapshot  # noqa: E402

from pursue_index.ingest_run import promote_snapshot  # noqa: E402
from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv  # noqa: E402
from pursue_index.scrape.manifest import save_manifest  # noqa: E402
from pursue_index.scrape.snapshots import _rebuild_index  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_URL = "https://www.war.gov/UFO/uap-data.csv"
_HEADER = "Release Date,Title,Type,Agency,Incident Date,PDF | Image Link"
_U = "https://www.war.gov/medialink/case_{:04d}.pdf"


def _csv(rows: list[tuple[str, str, str, int]]) -> bytes:
    body = "\r\n".join(f'{r},"{t}",PDF,FBI,{i},{_U.format(n)}' for r, t, i, n in rows)
    return ("﻿" + _HEADER + "\r\n" + body + "\r\n").encode("utf-8")


_PRIOR = _csv([("10/23/2026", "Case 1", "1/18/1957", 1)])
_NEW = _csv([("10/23/26", "Case 1", "1/18/57", 1), ("10/23/26", "Case 2", "1/18/57", 2)])
_SHA = build_manifest(_NEW, parse_csv(_NEW), _URL).csv_sha256
_CASE2 = parse_csv(_NEW)[1].card_id


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "manifests").mkdir(parents=True)
    save_manifest(build_manifest(_PRIOR, parse_csv(_PRIOR), _URL),
                  tmp_path / "data" / "manifests" / "latest.json")
    (tmp_path / "new.csv").write_bytes(_NEW)
    return tmp_path


def _dirs(root: Path) -> tuple[Path, Path]:
    return (root / "data" / "manifests" / "snapshots",
            root / "web" / "public" / "data" / "snapshots")


def _poll(root: Path) -> int:
    canonical, public = _dirs(root)
    return poll_snapshot.main([
        "--csv", str(root / "new.csv"), "--latest", str(root / "data/manifests/latest.json"),
        "--date-resolutions", str(root / "data" / "date_resolutions.json"),
        "--canonical-dir", str(canonical), "--public-dir", str(public),
        "--diff-out", str(root / "data" / "manifests" / "diffs" / f"{_SHA}.json")])


def _resolve(root: Path) -> None:
    (root / "data" / "date_resolutions.json").write_text(json.dumps({"entries": [
        {"card_id": _CASE2, "field": "incident_date", "value": "1/18/1957",
         "curator": "operator", "approved_at": "2026-11-20T12:00:00Z"}]}), encoding="utf-8")


def _entries(root: Path) -> tuple[list[dict], list[dict]]:
    canonical, public = _dirs(root)
    return (json.loads((canonical / "index.json").read_text())["snapshots"],
            json.loads((public / "index.json").read_text()))


def _for_sha(entries: list[dict]) -> list[dict]:
    return [e for e in entries if e["filename"].startswith(_SHA)]


def test_a_new_variant_replaces_its_shas_entry_in_both_indexes(root: Path) -> None:
    assert _poll(root) == 0
    _resolve(root)
    assert _poll(root) == 0
    canonical, public = _entries(root)
    variant = next(_dirs(root)[0].glob(f"{_SHA}.r*.json"))
    digest = json.loads(variant.read_text())["resolutions_digest"]
    for entries in (canonical, public):
        assert [(e["filename"], e["resolutions_digest"]) for e in _for_sha(entries)] == [
            (variant.name, digest)]
    assert len(canonical) == len(public) == 2  # the prior sha keeps its one entry


def test_promoting_a_variant_lists_it_as_the_shas_entry(root: Path) -> None:
    assert _poll(root) == 0
    _resolve(root)
    assert _poll(root) == 0
    _, public = _dirs(root)
    (public / "index.json").unlink()
    shutil.copy(next(_dirs(root)[0].glob(f"{_SHA}.json")), public / f"{_SHA}.json")
    variant = next(_dirs(root)[0].glob(f"{_SHA}.r*.json"))
    (root / "web" / "src" / "data").mkdir(parents=True)
    promote_snapshot(variant, root / "data" / "manifests" / "latest.json")
    assert [e["filename"] for e in _for_sha(_entries(root)[1])] == [variant.name]


def test_without_variants_both_indexes_keep_their_bytes(tmp_path: Path) -> None:
    """Pinned: the index bytes these three committed snapshots rebuild to."""
    canonical, public = tmp_path / "c", tmp_path / "p"
    canonical.mkdir()
    public.mkdir()
    for prefix in ("096ef2c0058a", "92b3ec7dd872", "c3f8209ef5f5"):
        snap = next((_REPO / "data" / "manifests" / "snapshots").glob(f"{prefix}*.json"))
        shutil.copy(snap, canonical / snap.name)
        shutil.copy(snap, public / snap.name)
    _rebuild_index(canonical, public)
    digests = [hashlib.sha256((d / "index.json").read_bytes()).hexdigest()
               for d in (canonical, public)]
    assert digests == ["5000e7cc6e3035d2b3743d70560c07a9a4185c5d243a2d338573d9bc03663792",
                       "ccfd5d0c4d4285d515e3a77fbcd62e934d55a52a53a50f7425d1b80f54f29e64"]


def test_committed_public_index_rebuilds_byte_identically(tmp_path: Path) -> None:
    public = tmp_path / "p"
    shutil.copytree(_REPO / "web" / "public" / "data" / "snapshots", public)
    before = (public / "index.json").read_bytes()
    from pursue_index.scrape.snapshots import write_public_index

    write_public_index(public)
    assert (public / "index.json").read_bytes() == before


def test_runbook_rotation_keeps_one_entry_per_sha(root: Path, monkeypatch) -> None:
    import runbook_snapshot_rotate as rb

    assert _poll(root) == 0
    _resolve(root)
    assert _poll(root) == 0
    canonical, public = _dirs(root)
    variant = next(canonical.glob(f"{_SHA}.r*.json"))
    monkeypatch.setattr(rb, "_REPO_ROOT", root)
    monkeypatch.setattr(rb, "SNAPSHOTS_PIPELINE", canonical)
    monkeypatch.setattr(rb, "SNAPSHOTS_WEB", public)
    rb.rotate(json.loads(variant.read_text()))
    for entries in _entries(root):
        assert [e["filename"] for e in _for_sha(entries)] == [variant.name]
    shas = [e["csv_sha256"] for e in _entries(root)[0]]
    assert len(shas) == len(set(shas))
