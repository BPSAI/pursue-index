"""Staleness needs an independent signal (security-gate fix round).

A strict row subset of the current manifest is a candidate removal tranche
(upstream takedowns), and a first-seen sha with an older ``Last-Modified``
is unconfirmed (clock skew), not stale. Neither is dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_poll_stale_edge import (
    _CURRENT_CSV,
    _SUBSET_CSV,
    LM_19E6,
    LM_NEW,
    SHA_19E6,
    SHA_C3F8,
    _bytes,
    _opens_tranche_issue,
    _poll_run,
    _Repo,
    _seeded_guard,
    _sha_resp,
    _Upstream,
    _write_current_manifest,
    poll_pursue,
    upstream,  # noqa: F401  (pytest fixture)
)


def _removal_repo(tmp_path: Path) -> _Repo:
    sha = poll_pursue.sha256_hex(_CURRENT_CSV)
    repo = _Repo(tmp_path / "repo")
    repo.archive.mkdir(parents=True)
    repo.diffs.mkdir(parents=True)
    repo.state.write_text(f"{sha}  2026-09-18T15:06:36Z\n")
    (repo.archive / f"{sha}.csv").write_bytes(_CURRENT_CSV)
    repo.guard.write_text(json.dumps(_seeded_guard(sha, [sha], LM_NEW), indent=2) + "\n")
    _write_current_manifest(repo, _CURRENT_CSV)
    return repo


def test_subset_csv_is_a_removal_tranche_not_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream  # noqa: F811
) -> None:
    repo = _removal_repo(tmp_path)
    upstream.serve((_SUBSET_CSV, None), (_CURRENT_CSV, None))

    first = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert first.status == "pending"  # a candidate, never dropped as stale
    upstream.serve((_SUBSET_CSV, None))
    second = _poll_run(repo, tmp_path, monkeypatch, 1)
    assert second.status == "changed"
    assert _opens_tranche_issue(second)
    assert repo.last_known() == poll_pursue.sha256_hex(_SUBSET_CSV)


def test_exact_byte_match_with_archived_older_copy_stays_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream  # noqa: F811
) -> None:
    repo = _removal_repo(tmp_path)
    older = poll_pursue.sha256_hex(_SUBSET_CSV)
    (repo.archive / f"{older}.csv").write_bytes(_SUBSET_CSV)
    cur = poll_pursue.sha256_hex(_CURRENT_CSV)
    repo.guard.write_text(json.dumps(_seeded_guard(cur, [older, cur], LM_NEW), indent=2) + "\n")
    upstream.serve((_SUBSET_CSV, None))

    assert _poll_run(repo, tmp_path, monkeypatch, 0).status == "stale"


def test_classify_first_seen_older_last_modified_is_unconfirmed() -> None:
    from _poll_guard import GuardState

    guard = GuardState(current_sha=SHA_C3F8, current_last_modified=LM_NEW, seen=[SHA_C3F8])
    assert guard.classify(SHA_19E6, LM_19E6) == "unconfirmed"


def test_classify_seen_before_older_last_modified_stays_stale() -> None:
    from _poll_guard import GuardState

    guard = GuardState(current_sha=SHA_C3F8, current_last_modified=LM_NEW, seen=[SHA_19E6, SHA_C3F8])
    assert guard.classify(SHA_19E6, LM_19E6) == "stale"


def test_clock_skew_new_sha_is_kept_polling_then_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream  # noqa: F811
) -> None:
    """Upstream clock behind: a genuinely new sha carries an older
    Last-Modified. It must not be dropped; two sightings declare it."""
    repo = _Repo(tmp_path / "repo")
    repo.archive.mkdir(parents=True)
    repo.diffs.mkdir(parents=True)
    repo.state.write_text(f"{SHA_C3F8}  2026-09-18T15:06:36Z\n")
    (repo.archive / f"{SHA_C3F8}.csv").write_bytes(_bytes(SHA_C3F8))
    repo.guard.write_text(json.dumps(_seeded_guard(SHA_C3F8, [SHA_C3F8], LM_NEW), indent=2) + "\n")
    upstream.serve(_sha_resp(SHA_19E6), _sha_resp(SHA_C3F8))

    first = _poll_run(repo, tmp_path, monkeypatch, 0)
    assert first.status == "pending"
    assert repo.last_known() == SHA_C3F8

    upstream.serve(_sha_resp(SHA_19E6))
    assert _poll_run(repo, tmp_path, monkeypatch, 1).status == "changed"
