"""Offline snapshot + diff generator.

The credential-free poll lane fetches the CSV bytes elsewhere and hands
them to ``generate_snapshot_diff`` — a network-free, R2-free entry point
that parses the bytes, rotates the prior ``latest.json`` into the public
snapshot mirror, writes the new manifest as ``snapshots/<new_sha>.json``
so the DiffIsland has both sides immediately, and reports the
added/removed cards, per-card field changes, and any brand-new CSV
column header.

These tests pin that contract end-to-end without touching the network
or any credential — bytes go in, snapshot files + a structured diff
come out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.poll_snapshot import (
    SnapshotDiffResult,
    generate_snapshot_diff,
)

_SOURCE_URL = "https://www.war.gov/UFO/uap-data.csv"

_HEADER = (
    "Redaction,Release Date,Title,Type,Agency,Incident Date,"
    "Incident Location,PDF | Image Link,Modal Image,Description Blurb"
)


def _row(title: str, url: str, agency: str = "FBI") -> str:
    return (
        f'False,5/8/26,"{title}",PDF,{agency},1/15/95,'
        f'"Roswell, NM",{url},https://www.war.gov/img/x.jpg,"desc"'
    )


def _csv(rows: list[str], header: str = _HEADER) -> bytes:
    body = "\r\n".join(rows)
    return ("﻿" + header + "\r\n" + body + "\r\n").encode("utf-8")


_URL1 = "https://www.war.gov/medialink/case_0001.pdf"
_URL2 = "https://www.war.gov/medialink/case_0002.pdf"


def _seed_latest(latest: Path, raw: bytes) -> str:
    """Build a prior ``latest.json`` from CSV bytes via the real parse
    path so card_ids line up with what the generator computes. Returns
    the prior manifest's csv_sha256.
    """
    manifest = build_manifest(raw, parse_csv(raw), _SOURCE_URL)
    save_manifest(manifest, latest)
    return manifest.csv_sha256


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "latest.json",
        tmp_path / "canonical",
        tmp_path / "public",
    )


def test_writes_new_snapshot_and_returns_added_removed(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))

    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])
    new_sha = build_manifest(new_raw, parse_csv(new_raw), _SOURCE_URL).csv_sha256

    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert isinstance(result, SnapshotDiffResult)
    # New manifest is snapshotted under its own sha in the public mirror.
    snap = public / f"{new_sha}.json"
    assert snap.exists()
    assert json.loads(snap.read_text())["csv_sha256"] == new_sha
    # One card added, none removed.
    assert [c.title for c in result.added] == ["Case 0002"]
    assert result.removed == []


def test_rotates_prior_latest_into_snapshots(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)
    prior_sha = _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))

    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])
    generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    # The prior latest.json is preserved as a public + canonical snapshot.
    assert (public / f"{prior_sha}.json").exists()
    assert (canonical / f"{prior_sha}.json").exists()


def test_existing_snapshot_is_immutable_on_rerun(tmp_path: Path) -> None:
    """Content-addressed ``<sha>.json`` is immutable: a rerun for the same
    CSV must not rewrite an existing snapshot (a fresh build would churn
    ``fetched_at`` + the index ordering). Mirrors ``rotate_to_snapshot``'s
    idempotency for the new-side writer.
    """
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))
    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])
    new_sha = build_manifest(new_raw, parse_csv(new_raw), _SOURCE_URL).csv_sha256

    generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    # Stamp a sentinel into the content-addressed snapshot to detect any rewrite.
    sentinel = b'{"sentinel": "immutable"}'
    (canonical / f"{new_sha}.json").write_bytes(sentinel)
    (public / f"{new_sha}.json").write_bytes(sentinel)

    # Re-run for the SAME csv — the existing snapshot must be left untouched.
    generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert (canonical / f"{new_sha}.json").read_bytes() == sentinel
    assert (public / f"{new_sha}.json").read_bytes() == sentinel


def test_detects_removed_card(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)]))

    new_raw = _csv([_row("Case 0001", _URL1)])
    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert [c.title for c in result.removed] == ["Case 0002"]
    assert result.added == []


def test_reports_field_changes_for_shared_card(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1, agency="FBI")]))

    new_raw = _csv([_row("Case 0001", _URL1, agency="CIA")])
    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert result.added == []
    assert result.removed == []
    assert len(result.field_changes) == 1
    change = result.field_changes[0]
    agency_diff = [d for d in change["diffs"] if d["field"] == "agency"]
    assert agency_diff == [{"field": "agency", "old": "FBI", "new": "CIA"}]


def test_reports_new_csv_column(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))

    new_header = _HEADER + ",Provenance Note"
    new_row = _row("Case 0001", _URL1) + ',"upstream note"'
    new_raw = _csv([new_row], header=new_header)

    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert result.new_columns == ["Provenance Note"]


def test_first_run_no_prior_latest(tmp_path: Path) -> None:
    latest, canonical, public = _dirs(tmp_path)  # latest.json does not exist

    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])
    new_sha = build_manifest(new_raw, parse_csv(new_raw), _SOURCE_URL).csv_sha256

    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )

    assert {c.title for c in result.added} == {"Case 0001", "Case 0002"}
    assert result.removed == []
    assert result.field_changes == []
    assert (public / f"{new_sha}.json").exists()


def test_makes_no_network_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The generator must never reach the network — bytes are passed in.
    Booby-trap both network seams so any call would explode.
    """
    from pursue_index.scrape import csv_fetcher

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("network call attempted in offline generator")

    monkeypatch.setattr(csv_fetcher, "http_get", _boom)
    monkeypatch.setattr(csv_fetcher, "fetch_raw_csv", _boom)

    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))
    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])

    result = generate_snapshot_diff(
        new_raw,
        source_url=_SOURCE_URL,
        latest_path=latest,
        canonical_dir=canonical,
        public_dir=public,
    )
    assert [c.title for c in result.added] == ["Case 0002"]


def test_new_side_snapshot_bytes_match_save_manifest(tmp_path: Path) -> None:
    """The new-side snapshot writer must produce byte-identical
    output to ``save_manifest``. DiffIsland reads snapshots written by BOTH this
    CI writer and a local ``scrape run`` rotation, so a forked serializer here
    could silently drift with no test catching it."""
    from pursue_index.scrape.poll_snapshot import _write_new_snapshot

    raw = _csv([_row("Case 0001", _URL1)])
    manifest = build_manifest(raw, parse_csv(raw), _SOURCE_URL)
    canonical, public = tmp_path / "canon", tmp_path / "pub"
    _write_new_snapshot(manifest, canonical, public)
    ref = tmp_path / "ref.json"
    save_manifest(manifest, ref)
    sha = manifest.csv_sha256
    assert (canonical / f"{sha}.json").read_bytes() == ref.read_bytes()
    # The public mirror is an exact byte copy of canonical.
    assert (public / f"{sha}.json").read_bytes() == (canonical / f"{sha}.json").read_bytes()


def test_backfill_missing_public_mirror_refreshes_index(tmp_path: Path) -> None:
    """Restoring a missing public mirror file on an immutable rerun
    must ALSO refresh the public index.json, else DiffIsland sees a snapshot
    file its index doesn't enumerate."""
    latest, canonical, public = _dirs(tmp_path)
    _seed_latest(latest, _csv([_row("Case 0001", _URL1)]))
    new_raw = _csv([_row("Case 0001", _URL1), _row("Case 0002", _URL2)])
    new_sha = build_manifest(new_raw, parse_csv(new_raw), _SOURCE_URL).csv_sha256
    generate_snapshot_diff(
        new_raw, source_url=_SOURCE_URL, latest_path=latest,
        canonical_dir=canonical, public_dir=public,
    )
    # Simulate a partial-mirror state: the public <sha>.json is gone and the
    # public index was rebuilt without it.
    (public / f"{new_sha}.json").unlink()
    (public / "index.json").write_text("[]", encoding="utf-8")
    # Re-run for the SAME csv: the immutable branch backfills the mirror...
    generate_snapshot_diff(
        new_raw, source_url=_SOURCE_URL, latest_path=latest,
        canonical_dir=canonical, public_dir=public,
    )
    assert (public / f"{new_sha}.json").exists()  # mirror restored
    assert new_sha in (public / "index.json").read_text()  # ...AND re-enumerated
