"""Tests for the lightweight tranche-poll script.

The poll runs from GitHub Actions on a cron schedule. It calls
``pursue_index.scrape.csv_fetcher`` for the actual fetch (so the
curl_cffi + Chrome-TLS contract is reused exactly), hashes the bytes,
compares to a committed last-known sha, and emits a structured result
the workflow can act on (commit a new sha file, open an issue, exit).

These tests pin the contract for each branch:

* unchanged   -> Unchanged result, no side effects
* changed     -> Changed result with both shas + issue payload
* fetch fails -> Failed result with error + failure-issue payload
* missing last-known file -> treated as a prior-unknown observation
* CLI entrypoint -> exits 0 on success, 1 on fetch failure, writes the
  new-sha file on change only

The script is run from a clean GitHub-hosted runner each invocation,
so no mocking of curl_cffi is needed for the live workflow — but for
unit tests we stub ``fetch_raw_csv`` exactly the way ``test_csv_fetcher``
does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; add it to sys.path so the module imports
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import poll_pursue  # noqa: E402


_BODY_A = b"col1,col2\r\nfoo,bar\r\n"
_BODY_B = b"col1,col2\r\nfoo,bar\r\nbaz,qux\r\n"
# sha256 of _BODY_A and _BODY_B precomputed by the implementation, not
# hard-coded here — the tests assert *equality*, not specific digests.


def _stub_fetch(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    monkeypatch.setattr(poll_pursue, "fetch_raw_csv", lambda: body)


def _stub_fetch_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _raise() -> bytes:
        raise exc

    monkeypatch.setattr(poll_pursue, "fetch_raw_csv", _raise)


def test_unchanged_when_sha_matches_last_known(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Unchanged)
    assert result.sha == sha_a
    assert state.read_text().startswith(sha_a)  # file untouched


def test_changed_returns_old_and_new_sha_and_issue_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch(monkeypatch, _BODY_B)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Changed)
    assert result.old_sha == sha_a
    assert result.new_sha == poll_pursue.sha256_hex(_BODY_B)
    assert result.old_sha != result.new_sha
    assert "tranche-detected" in result.issue_labels
    assert sha_a in result.issue_body
    assert result.new_sha in result.issue_body
    # The state file is NOT yet written by poll() — that's the CLI's job
    # so a dry-run can still report the diff without mutating disk.
    assert state.read_text().startswith(sha_a)


def test_fetch_failure_returns_failed_with_error_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch_raises(monkeypatch, RuntimeError("HTTP 403"))
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Failed)
    assert "HTTP 403" in result.error
    assert "tranche-poll-failure" in result.issue_labels
    assert "HTTP 403" in result.issue_body


def test_empty_body_treated_as_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch(monkeypatch, b"")
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Failed)
    assert "empty" in result.error.lower()
    assert "tranche-poll-failure" in result.issue_labels


def test_missing_last_known_file_is_first_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    # state file does not exist on disk

    result = poll_pursue.poll(state)

    # First observation: no prior to compare to. We return Changed with
    # old_sha empty so the workflow records the bootstrap commit, but
    # we DON'T emit a tranche-detected issue (nothing has actually
    # changed — we just hadn't been watching yet).
    assert isinstance(result, poll_pursue.Changed)
    assert result.old_sha == ""
    assert result.new_sha == poll_pursue.sha256_hex(_BODY_A)
    assert result.is_bootstrap is True


def test_cli_main_exits_zero_when_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    original = f"{sha_a}  2026-05-08T00:00:00Z\n"
    state.write_text(original)

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 0
    assert state.read_text() == original  # unchanged on disk


def test_cli_main_writes_new_sha_when_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch(monkeypatch, _BODY_B)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 0
    written = state.read_text()
    assert written.startswith(poll_pursue.sha256_hex(_BODY_B))
    # Single line, two-space-separated, terminating newline
    assert written.endswith("\n")
    assert written.count("\n") == 1


def test_cli_main_exits_nonzero_on_fetch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_fetch_raises(monkeypatch, RuntimeError("HTTP 503"))
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 1


def test_cli_main_writes_github_outputs_on_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When GITHUB_OUTPUT is set, the CLI emits machine-readable kv pairs
    so the workflow can branch on ``status=changed|unchanged|failed``
    and pull the issue title/body out without re-parsing the script's
    stdout. This is the contract the workflow file relies on.
    """
    _stub_fetch(monkeypatch, _BODY_B)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")
    gh_out = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 0
    out = gh_out.read_text()
    assert "status=changed" in out
    assert f"old_sha={sha_a}" in out
    assert f"new_sha={poll_pursue.sha256_hex(_BODY_B)}" in out


def test_idempotent_hashing() -> None:
    """Same bytes -> same sha across calls. Pins the spec wording in the
    task description: 'the poll script must be idempotent: re-running
    with the same upstream produces the same sha'.
    """
    assert poll_pursue.sha256_hex(_BODY_A) == poll_pursue.sha256_hex(_BODY_A)
    assert poll_pursue.sha256_hex(_BODY_A) != poll_pursue.sha256_hex(_BODY_B)
