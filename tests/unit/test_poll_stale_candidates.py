"""#176: a never-seen sha is a candidate unless an independent signal says otherwise.

A never-seen sha with a newer or equal ``Last-Modified``, or with rows the
current manifest has never seen, still goes through confirm-then-declare;
plus the two pure helpers behind those decisions. Shared fixtures live in
``test_poll_stale_edge``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_poll_stale_edge import (
    _CURRENT_CSV,
    _DISJOINT_CSV,
    _SUBSET_CSV,
    LM_19E6,
    LM_NEW,
    SHA_19E6,
    SHA_C3F8,
    _bytes,
    _make_repo,
    _poll_run,
    _Repo,
    _seeded_guard,
    _sha_resp,
    _Upstream,
    _write_current_manifest,
    poll_pursue,
)
from tests.unit.test_poll_stale_edge import (
    upstream as _upstream_fixture,
)

upstream = _upstream_fixture  # re-exported so pytest finds the shared fixture


def test_never_seen_sha_with_newer_last_modified_is_still_pending_then_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """Regression: a never-seen sha with a strictly newer Last-Modified
    must still go through the normal confirm-then-declare path."""
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6))
    upstream.serve(_sha_resp(SHA_C3F8), _sha_resp(SHA_19E6))

    first = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert first.status == "pending"
    assert repo.last_known() == SHA_19E6

    upstream.serve(_sha_resp(SHA_C3F8))
    second = _poll_run(repo, tmp_path, monkeypatch, 1)

    assert second.status == "changed"
    assert repo.last_known() == SHA_C3F8


def test_never_seen_sha_with_equal_last_modified_stays_a_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """A never-seen sha whose Last-Modified exactly matches the current
    sha's isn't *older*, so it still has to earn its stripes via the
    confirm-then-declare path, not get waved through as stale."""
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_NEW))
    upstream.serve((_bytes(SHA_C3F8), LM_NEW))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "pending"


def test_never_seen_sha_with_disjoint_rows_is_a_candidate_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """Regression: a never-seen sha whose rows are NOT a subset (some rows
    the manifest has never seen) must not be waved through as stale just
    because it also lacks a Last-Modified header."""
    current_sha = poll_pursue.sha256_hex(_CURRENT_CSV)
    repo = _Repo(tmp_path / "repo")
    repo.archive.mkdir(parents=True)
    repo.diffs.mkdir(parents=True)
    repo.state.write_text(f"{current_sha}  2026-09-18T15:06:36Z\n")
    (repo.archive / f"{current_sha}.csv").write_bytes(_CURRENT_CSV)
    repo.guard.write_text(json.dumps(_seeded_guard(current_sha, [current_sha], LM_NEW), indent=2) + "\n")
    _write_current_manifest(repo, _CURRENT_CSV)
    upstream.serve((_DISJOINT_CSV, None), (_DISJOINT_CSV, None))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "changed"


def test_is_strictly_older_true_only_when_both_parse_and_candidate_is_earlier() -> None:
    from _poll_guard import is_strictly_older

    assert is_strictly_older(LM_19E6, LM_NEW) is True
    assert is_strictly_older(LM_NEW, LM_19E6) is False  # candidate newer
    assert is_strictly_older(LM_NEW, LM_NEW) is False  # equal
    assert is_strictly_older(None, LM_NEW) is False
    assert is_strictly_older(LM_19E6, None) is False
    assert is_strictly_older("not a date", LM_NEW) is False


def test_is_row_subset_of_manifest(tmp_path: Path) -> None:
    from _poll_stale_checks import is_row_subset_of_manifest

    from pursue_index.scrape.csv_fetcher import build_manifest, parse_csv
    from pursue_index.scrape.manifest import save_manifest

    manifest_path = tmp_path / "latest.json"
    manifest = build_manifest(_CURRENT_CSV, parse_csv(_CURRENT_CSV), "https://example.test/csv")
    save_manifest(manifest, manifest_path)

    assert is_row_subset_of_manifest(manifest_path, _SUBSET_CSV) is True
    assert is_row_subset_of_manifest(manifest_path, _CURRENT_CSV) is False  # equal, not strict
    assert is_row_subset_of_manifest(manifest_path, _DISJOINT_CSV) is False
    assert is_row_subset_of_manifest(tmp_path / "missing.json", _SUBSET_CSV) is False
    assert is_row_subset_of_manifest(None, _SUBSET_CSV) is False
    assert is_row_subset_of_manifest(manifest_path, b"not,a\nvalid csv\x00\xff") is False
