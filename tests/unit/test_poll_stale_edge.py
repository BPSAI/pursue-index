"""Stale-edge guard for the tranche poller (#157).

From 2026-09-24 upstream served ``c3f8209ef5f5`` consistently, but the
poller was intermittently handed the previous tranche (``19e6dd7a69d5``)
and a Mac Roman re-export of the new content (``e1f9fec8d74a``) by stale
cache edges. Every flip was recorded as an upstream change.

These tests drive ``poll_pursue.main`` end to end with only the HTTP layer
(``csv_fetcher.http_get``) mocked, using the committed CSV bytes:

* a sha seen before the current one is a stale-edge observation unless its
  ``Last-Modified`` is strictly newer (no commit, no issue, no snapshot);
* a never-seen sha is declared only once it is fetched twice in a row
  (an immediate in-run re-fetch, or the next run when the re-fetch
  disagreed);
* a confirmed change that only re-encodes the same text is ``benign``;
* the snapshot lane never rewrites an existing diff record.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_pursue  # noqa: E402
import poll_snapshot  # noqa: E402

from pursue_index.scrape import csv_fetcher  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_CSV_DIR = _REPO / "data" / "raw" / "csv"
_DIFFS = _REPO / "data" / "manifests" / "diffs"

SHA_19E6 = "19e6dd7a69d5c41c30bc3d9302462e922c6225cf18649298b329e68918e28a20"
SHA_E1F9 = "e1f9fec8d74a1044f11c2fa1f5be53937cbab78485ec90d045d2ed06ca491fb5"
SHA_C3F8 = "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7"

LM_19E6 = "Fri, 18 Sep 2026 15:05:12 GMT"
LM_NEW = "Thu, 24 Sep 2026 17:33:32 GMT"  # served with both e1f9 and c3f8
LM_LATER = "Mon, 28 Sep 2026 09:00:00 GMT"

_LM = {SHA_19E6: LM_19E6, SHA_E1F9: LM_NEW, SHA_C3F8: LM_NEW}


def _bytes(sha: str) -> bytes:
    return (_CSV_DIR / f"{sha}.csv").read_bytes()


@dataclass
class _Resp:
    content: bytes
    headers: dict[str, str]
    status_code: int = 200

    def raise_for_status(self) -> None:
        return None


@dataclass
class _Upstream:
    """Queue of (bytes, Last-Modified) responses served by the fake edge."""

    queue: deque[tuple[bytes, str | None]] = field(default_factory=deque)
    requests: int = 0

    def serve(self, *items: tuple[bytes, str | None]) -> None:
        self.queue.extend(items)

    def get(self, url: str, **_: object) -> _Resp:
        self.requests += 1
        body, lm = self.queue.popleft()
        headers = {"Last-Modified": lm} if lm else {}
        return _Resp(content=body, headers=headers)


def _sha_resp(sha: str) -> tuple[bytes, str | None]:
    return _bytes(sha), _LM[sha]


@pytest.fixture()
def upstream(monkeypatch: pytest.MonkeyPatch) -> _Upstream:
    fake = _Upstream()
    monkeypatch.setattr(csv_fetcher, "http_get", fake.get)
    return fake


@dataclass
class _Repo:
    """A tmp copy of the repo paths the poll + snapshot lanes touch."""

    root: Path

    @property
    def state(self) -> Path:
        return self.root / "data" / "last-known-csv-sha.txt"

    @property
    def guard(self) -> Path:
        return self.root / "data" / "poll-state.json"

    @property
    def archive(self) -> Path:
        return self.root / "data" / "raw" / "csv"

    @property
    def diffs(self) -> Path:
        return self.root / "data" / "manifests" / "diffs"

    @property
    def latest(self) -> Path:
        return self.root / "data" / "manifests" / "latest.json"

    def last_known(self) -> str:
        return self.state.read_text().split()[0]


def _make_repo(tmp_path: Path, current: str, *, archived: tuple[str, ...] = (), guard: dict | None = None) -> _Repo:
    repo = _Repo(tmp_path / "repo")
    repo.archive.mkdir(parents=True)
    repo.diffs.mkdir(parents=True)
    repo.state.write_text(f"{current}  2026-09-18T15:06:36Z\n")
    for sha in {current, *archived}:
        shutil.copy(_CSV_DIR / f"{sha}.csv", repo.archive / f"{sha}.csv")
    if guard is not None:
        repo.guard.write_text(json.dumps(guard, indent=2) + "\n")
    return repo


def _seeded_guard(current: str, seen: list[str], lm: str | None) -> dict:
    return {
        "current_sha": current,
        "current_last_modified": lm,
        "pending": None,
        "seen": seen,
    }


@dataclass
class _Run:
    status: str
    outputs: dict[str, str]
    summary: str


def _parse_outputs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if "<<" in line and "=" not in line.split("<<", 1)[0]:
            key, delim = line.split("<<", 1)
            body = []
            for inner in lines:
                if inner == delim:
                    break
                body.append(inner)
            out[key] = "\n".join(body)
        elif "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def _poll_run(repo: _Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n: int) -> _Run:
    gh_out = tmp_path / f"out-{n}.txt"
    summary = tmp_path / f"summary-{n}.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = poll_pursue.main([
        "--state", str(repo.state),
        "--guard-state", str(repo.guard),
        "--manifest", str(repo.latest),
        "--csv-archive-dir", str(repo.archive),
    ])
    assert rc == 0
    outputs = _parse_outputs(gh_out.read_text())
    return _Run(
        status=outputs["status"],
        outputs=outputs,
        summary=summary.read_text() if summary.exists() else "",
    )


def _opens_tranche_issue(run: _Run) -> bool:
    """The workflow's `Open tranche-detected issue` gate."""
    return run.status == "changed" and run.outputs.get("is_bootstrap") == "false"


def _snapshot_lane(repo: _Repo, run: _Run) -> int:
    """The snapshot job, gated like the workflow (status == 'changed')."""
    new_sha = run.outputs["new_sha"]
    return poll_snapshot.main([
        "--csv", str(repo.archive / f"{new_sha}.csv"),
        "--latest", str(repo.latest),
        "--canonical-dir", str(repo.root / "snapshots"),
        "--public-dir", str(repo.root / "public-snapshots"),
        "--diff-out", str(repo.diffs / f"{new_sha}.json"),
    ])


# ---------------------------------------------------------------------------
# Replay of the 2026-09-24 sequence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guard_file", ["seeded", "absent"])
def test_replay_2026_09_24_declares_exactly_one_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream: _Upstream,
    guard_file: str,
) -> None:
    guard = _seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6) if guard_file == "seeded" else None
    repo = _make_repo(tmp_path, SHA_19E6, guard=guard)
    shutil.copy(_REPO / "data" / "manifests" / "latest.json", repo.latest)
    for sha in (SHA_19E6, SHA_C3F8):
        shutil.copy(_DIFFS / f"{sha}.json", repo.diffs / f"{sha}.json")
    record_19e6 = (repo.diffs / f"{SHA_19E6}.json").read_bytes()

    sequence = [SHA_19E6, SHA_E1F9, SHA_C3F8, SHA_19E6, SHA_C3F8, SHA_19E6, SHA_C3F8]
    upstream.serve(*(_sha_resp(s) for s in sequence))

    runs: list[_Run] = []
    commits = 0
    while upstream.queue:
        state_before = repo.state.read_bytes()
        run = _poll_run(repo, tmp_path, monkeypatch, len(runs))
        runs.append(run)
        if run.status == "changed":
            assert _snapshot_lane(repo, run) == 0
        if repo.state.read_bytes() != state_before:
            commits += 1

    declared = [r for r in runs if r.status in ("changed", "benign")]
    assert len(declared) == 1
    assert declared[0].status == "changed"
    assert declared[0].outputs["old_sha"] == SHA_19E6
    assert declared[0].outputs["new_sha"] == SHA_C3F8
    assert sum(_opens_tranche_issue(r) for r in runs) == 1
    assert commits == 1  # last-known-csv-sha.txt moved exactly once
    assert repo.last_known() == SHA_C3F8
    assert (repo.diffs / f"{SHA_19E6}.json").read_bytes() == record_19e6
    assert not (repo.diffs / f"{SHA_E1F9}.json").exists()
    assert upstream.requests == len(sequence)
    stale = [r for r in runs if r.status == "stale"]
    assert stale and all("stale-edge" in r.summary for r in stale)


def test_replay_of_a_clean_single_change_keeps_full_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """A genuine tranche (new bytes, newer Last-Modified, served steadily)
    is declared on the first run, opens the issue, gets its snapshot + diff,
    and moves last-known: the pre-#157 behaviour, one extra request."""
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6))
    shutil.copy(_REPO / "data" / "manifests" / "latest.json", repo.latest)
    upstream.serve(*[_sha_resp(SHA_C3F8)] * 3)

    first = _poll_run(repo, tmp_path, monkeypatch, 0)
    assert first.status == "changed"
    assert _opens_tranche_issue(first)
    assert first.outputs["issue_title"] == f"PURSUE tranche detected: {SHA_C3F8[:12]}"
    assert SHA_19E6 in first.outputs["issue_body"]
    assert upstream.requests == 2  # fetch + confirming re-fetch
    assert repo.last_known() == SHA_C3F8
    assert _snapshot_lane(repo, first) == 0
    art = json.loads((repo.diffs / f"{SHA_C3F8}.json").read_text())
    assert art["new_sha"] == SHA_C3F8
    assert (repo.root / "snapshots" / f"{SHA_C3F8}.json").exists()
    guard = json.loads(repo.guard.read_text())
    assert guard["current_sha"] == SHA_C3F8
    assert guard["current_last_modified"] == LM_NEW
    assert guard["pending"] is None

    second = _poll_run(repo, tmp_path, monkeypatch, 1)
    assert second.status == "unchanged"
    assert upstream.requests == 3


# ---------------------------------------------------------------------------
# (1) No regressions
# ---------------------------------------------------------------------------


def test_previously_seen_sha_with_older_last_modified_is_stale_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    guard = _seeded_guard(SHA_C3F8, [SHA_19E6, SHA_C3F8], LM_NEW)
    repo = _make_repo(tmp_path, SHA_C3F8, archived=(SHA_19E6,), guard=guard)
    state_before, guard_before = repo.state.read_bytes(), repo.guard.read_bytes()
    upstream.serve(_sha_resp(SHA_19E6))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "stale"
    assert not _opens_tranche_issue(run)
    assert repo.state.read_bytes() == state_before
    assert repo.guard.read_bytes() == guard_before
    assert "stale-edge" in run.summary and SHA_19E6[:12] in run.summary
    assert upstream.requests == 1


def test_previously_seen_sha_with_equal_last_modified_is_stale_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """e1f9 re-served after c3f8 became current, same Last-Modified."""
    guard = _seeded_guard(SHA_C3F8, [SHA_19E6, SHA_E1F9, SHA_C3F8], LM_NEW)
    repo = _make_repo(tmp_path, SHA_C3F8, archived=(SHA_E1F9,), guard=guard)
    upstream.serve(_sha_resp(SHA_E1F9))

    assert _poll_run(repo, tmp_path, monkeypatch, 0).status == "stale"
    assert repo.last_known() == SHA_C3F8


def test_previously_seen_sha_with_strictly_newer_last_modified_is_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """A genuine revert (upstream re-publishes old bytes) still counts."""
    guard = _seeded_guard(SHA_C3F8, [SHA_19E6, SHA_C3F8], LM_NEW)
    repo = _make_repo(tmp_path, SHA_C3F8, archived=(SHA_19E6,), guard=guard)
    upstream.serve((_bytes(SHA_19E6), LM_LATER), (_bytes(SHA_19E6), LM_LATER))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "changed"
    assert repo.last_known() == SHA_19E6
    assert json.loads(repo.guard.read_text())["current_last_modified"] == LM_LATER


def test_missing_guard_state_treats_archived_shas_as_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """Fail closed without a guard file: every sha already in the byte
    archive was observed before the current one."""
    repo = _make_repo(tmp_path, SHA_C3F8, archived=(SHA_19E6, SHA_E1F9))
    upstream.serve(_sha_resp(SHA_19E6))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "stale"
    assert repo.last_known() == SHA_C3F8
    assert not repo.guard.exists()  # stale observations write nothing


# ---------------------------------------------------------------------------
# (3) Confirm before declaring
# ---------------------------------------------------------------------------


def test_unconfirmed_new_sha_is_pending_and_confirmed_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6))
    # Run 1: c3f8, then the re-fetch lands on an edge still serving 19e6.
    upstream.serve(_sha_resp(SHA_C3F8), _sha_resp(SHA_19E6))

    first = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert first.status == "pending"
    assert not _opens_tranche_issue(first)
    assert repo.last_known() == SHA_19E6
    guard = json.loads(repo.guard.read_text())
    assert guard["pending"]["sha"] == SHA_C3F8
    assert (repo.archive / f"{SHA_C3F8}.csv").exists()
    assert "pending" in first.summary

    # Run 2: c3f8 again -> the second consecutive sighting, no re-fetch.
    upstream.serve(_sha_resp(SHA_C3F8))
    second = _poll_run(repo, tmp_path, monkeypatch, 1)

    assert second.status == "changed"
    assert second.outputs["old_sha"] == SHA_19E6
    assert repo.last_known() == SHA_C3F8
    assert json.loads(repo.guard.read_text())["pending"] is None
    assert upstream.requests == 3


def test_a_different_new_sha_replaces_the_pending_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6))
    upstream.serve(_sha_resp(SHA_E1F9), _sha_resp(SHA_C3F8))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "pending"
    guard = json.loads(repo.guard.read_text())
    assert guard["pending"]["sha"] == SHA_C3F8
    assert guard["seen"] == [SHA_19E6, SHA_E1F9, SHA_C3F8]


def test_unchanged_poll_makes_a_single_request_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    guard = _seeded_guard(SHA_C3F8, [SHA_19E6, SHA_C3F8], LM_NEW)
    repo = _make_repo(tmp_path, SHA_C3F8, guard=guard)
    before = repo.guard.read_bytes()
    upstream.serve(_sha_resp(SHA_C3F8))

    assert _poll_run(repo, tmp_path, monkeypatch, 0).status == "unchanged"
    assert upstream.requests == 1
    assert repo.guard.read_bytes() == before


# ---------------------------------------------------------------------------
# (4) Encoding-only changes
# ---------------------------------------------------------------------------


def test_confirmed_encoding_only_change_is_benign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """Same text re-exported in a legacy codec (curly quotes, NBSP, no BOM)."""
    text = 'Title,Description Blurb\r\n"Case\u00a01","It\u2019s a \u201ctest\u201d"\r\n'
    utf8 = ("\ufeff" + text).encode("utf-8")
    legacy = text.encode("cp1252")
    sha_utf8, sha_legacy = poll_pursue.sha256_hex(utf8), poll_pursue.sha256_hex(legacy)
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(sha_utf8, [sha_utf8], LM_NEW))
    repo.state.write_text(f"{sha_utf8}  2026-09-24T17:33:37Z\n")
    (repo.archive / f"{sha_utf8}.csv").write_bytes(utf8)
    upstream.serve((legacy, LM_NEW), (legacy, LM_NEW))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "benign"
    assert not _opens_tranche_issue(run)
    assert run.outputs["old_sha"] == sha_utf8
    assert run.outputs["new_sha"] == sha_legacy
    assert repo.last_known() == sha_legacy
    assert "encoding-only" in run.summary
    # Stored data is never altered by the comparison.
    assert (repo.archive / f"{sha_utf8}.csv").read_bytes() == utf8


def test_real_e1f9_to_c3f8_is_a_declared_change_not_benign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """The committed pair differs in text (lossy U+202F, a trimmed trailing
    space), so it takes the normal change path: issue + snapshot."""
    guard = _seeded_guard(SHA_E1F9, [SHA_19E6, SHA_E1F9], LM_NEW)
    repo = _make_repo(tmp_path, SHA_E1F9, guard=guard)
    upstream.serve(_sha_resp(SHA_C3F8), _sha_resp(SHA_C3F8))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "changed"
    assert _opens_tranche_issue(run)
    assert repo.last_known() == SHA_C3F8


def test_confirmed_change_with_real_differences_is_not_benign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    repo = _make_repo(tmp_path, SHA_19E6, guard=_seeded_guard(SHA_19E6, [SHA_19E6], LM_19E6))
    upstream.serve(_sha_resp(SHA_E1F9), _sha_resp(SHA_E1F9))

    assert _poll_run(repo, tmp_path, monkeypatch, 0).status == "changed"


def test_missing_prior_bytes_fails_closed_to_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """Without the current sha's bytes the change can't be proven
    encoding-only, so it is declared (an alert, not a silent skip)."""
    guard = _seeded_guard(SHA_E1F9, [SHA_E1F9], LM_NEW)
    repo = _make_repo(tmp_path, SHA_E1F9, guard=guard)
    (repo.archive / f"{SHA_E1F9}.csv").unlink()
    upstream.serve(_sha_resp(SHA_C3F8), _sha_resp(SHA_C3F8))

    assert _poll_run(repo, tmp_path, monkeypatch, 0).status == "changed"


def test_stale_summary_sanitizes_the_upstream_last_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: _Upstream
) -> None:
    """The header is upstream-controlled: one line, printable, bounded."""
    guard = _seeded_guard(SHA_C3F8, [SHA_19E6, SHA_C3F8], LM_NEW)
    repo = _make_repo(tmp_path, SHA_C3F8, archived=(SHA_19E6,), guard=guard)
    hostile = "Fri, 18 Sep 2026 15:05:12 GMT\n## [click](https://x.invalid)" + "A" * 500
    upstream.serve((_bytes(SHA_19E6), hostile))

    run = _poll_run(repo, tmp_path, monkeypatch, 0)

    assert run.status == "stale"
    assert run.summary.count("\n") == 1
    assert "## [click]" not in run.summary
    assert len(run.summary) < 400


@pytest.mark.parametrize("bad_sha", ["../secret", "c3f8", "C3F8" + "0" * 60, ""])
def test_encoding_check_never_builds_a_path_from_a_malformed_sha(tmp_path: Path, bad_sha: str) -> None:
    """The prior sha comes from repo files; only a 64-hex sha may name an
    archive path. Anything else fails closed (not benign)."""
    from _poll_guard import encoding_only_vs_archive

    archive = tmp_path / "csv"
    archive.mkdir()
    body = _bytes(SHA_C3F8)
    (tmp_path / "secret.csv").write_bytes(body)
    (archive / f"{bad_sha}.csv").parent.mkdir(parents=True, exist_ok=True)
    if "/" not in bad_sha:
        (archive / f"{bad_sha}.csv").write_bytes(body)
    assert encoding_only_vs_archive(archive, bad_sha, body) is False
