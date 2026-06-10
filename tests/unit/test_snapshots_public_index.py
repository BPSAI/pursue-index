"""The web snapshot index must ship enriched {filename, fetched_at,
card_count} objects on EVERY writer path, not just the ingest/promote
one. The scrape-run path (rotate_to_snapshot -> _rebuild_index) is the
most-travelled; if it writes bare filenames it silently reverts the
/diff selector labels back to "?? cards" (regression caught in PR #82
review). These tests pin the public-index shape at the source.
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.scrape.snapshots import (
    build_public_index,
    rotate_to_snapshot,
    write_public_index,
)


def _write_manifest(path: Path, sha: str, fetched_at: str, n_cards: int) -> None:
    path.write_text(
        json.dumps(
            {
                "csv_sha256": sha,
                "fetched_at": fetched_at,
                "cards": [{"card_id": f"c{i}"} for i in range(n_cards)],
            }
        )
    )


def test_rotate_to_snapshot_writes_enriched_public_index(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    public = tmp_path / "public"
    canonical.mkdir()
    public.mkdir()
    latest = tmp_path / "latest.json"
    sha = "a" * 64
    _write_manifest(latest, sha, "2026-06-10T16:17:15Z", 3)

    rotate_to_snapshot(latest, canonical_dir=canonical, public_dir=public)

    index = json.loads((public / "index.json").read_text())
    assert index == [
        {"filename": f"{sha}.json", "fetched_at": "2026-06-10T16:17:15Z", "card_count": 3}
    ]


def test_build_public_index_sorts_oldest_first_with_counts(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    _write_manifest(public / ("1" * 64 + ".json"), "1" * 64, "2026-05-08T00:00:00Z", 161)
    _write_manifest(public / ("2" * 64 + ".json"), "2" * 64, "2026-06-10T00:00:00Z", 222)

    entries = build_public_index(public)

    assert [e["filename"][:1] for e in entries] == ["1", "2"]  # oldest first
    assert entries[0]["card_count"] == 161
    assert entries[1]["fetched_at"] == "2026-06-10T00:00:00Z"
    # index.json itself is never listed as a snapshot
    assert all(e["filename"] != "index.json" for e in entries)


def test_write_public_index_is_byte_stable(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    _write_manifest(public / ("3" * 64 + ".json"), "3" * 64, "2026-06-01T00:00:00Z", 5)

    write_public_index(public)
    first = (public / "index.json").read_bytes()
    write_public_index(public)
    assert (public / "index.json").read_bytes() == first
