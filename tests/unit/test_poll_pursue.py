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
    # state file does not exist on disk; pass manifest_path=None so
    # the manifest-fallback shortcut isn't engaged here (covered by
    # test_seeds_from_manifest_when_state_file_missing).

    result = poll_pursue.poll(state, manifest_path=None)

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


def test_cli_main_writes_github_outputs_on_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coverage for the unchanged branch of ``_emit_gh_outputs`` — only
    ``status`` and ``new_sha`` are emitted; no ``old_sha`` (would imply a
    diff that doesn't exist) and no ``issue_*`` keys (no issue is opened).
    """
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")
    gh_out = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 0
    out = gh_out.read_text()
    assert "status=unchanged" in out
    assert f"new_sha={sha_a}" in out
    assert "old_sha=" not in out
    assert "issue_title=" not in out
    assert "issue_body" not in out


def test_cli_main_writes_github_outputs_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coverage for the failed branch of ``_emit_gh_outputs`` — emits a
    ``tranche-poll-failure`` label, an issue title/body, and the error
    string so the workflow can open a failure issue.
    """
    _stub_fetch_raises(monkeypatch, RuntimeError("HTTP 503"))
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")
    gh_out = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 1
    out = gh_out.read_text()
    assert "status=failed" in out
    assert "issue_labels=tranche-poll-failure" in out
    assert "issue_title=PURSUE poll failed" in out
    assert "HTTP 503" in out


def test_emit_gh_outputs_uses_unique_heredoc_delimiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GH docs recommend a random delimiter so an ``EOF`` line in the
    issue body can't terminate the heredoc early. Pin the contract:
    if the body literally contains the word ``EOF`` on its own line,
    the workflow must still parse the value correctly.
    """
    body_with_eof_line = b"col1\r\nEOF\r\n"
    _stub_fetch(monkeypatch, body_with_eof_line)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")
    gh_out = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    rc = poll_pursue.main(["--state", str(state)])

    assert rc == 0
    out = gh_out.read_text()
    # The heredoc opener is "issue_body<<DELIMITER" where DELIMITER must
    # not be the literal "EOF". A random/uuid-based suffix is the
    # documented pattern.
    issue_body_lines = [ln for ln in out.splitlines() if ln.startswith("issue_body<<")]
    assert len(issue_body_lines) == 1
    delimiter = issue_body_lines[0].split("<<", 1)[1]
    assert delimiter != "EOF"
    assert len(delimiter) > 4  # has entropy beyond bare "EOF_"


def test_keyboard_interrupt_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual Ctrl-C must propagate, not get classified as a poll
    failure that opens a real GitHub issue.
    """

    def _raise_ctrl_c() -> bytes:
        raise KeyboardInterrupt

    monkeypatch.setattr(poll_pursue, "fetch_raw_csv", _raise_ctrl_c)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    with pytest.raises(KeyboardInterrupt):
        poll_pursue.poll(state)


def test_system_exit_is_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SystemExit`` from a nested ``sys.exit`` must propagate. Catching
    it would mask intentional exits and produce a misleading failure
    issue.
    """

    def _raise_exit() -> bytes:
        raise SystemExit(2)

    monkeypatch.setattr(poll_pursue, "fetch_raw_csv", _raise_exit)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    with pytest.raises(SystemExit):
        poll_pursue.poll(state)


def test_failed_extra_carries_exception_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Failed.extra`` must be populated for diagnostics — at minimum
    the exception type so the operator can triage from the issue body
    without grepping the workflow log.
    """
    _stub_fetch_raises(monkeypatch, ConnectionError("name resolution failed"))
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Failed)
    assert result.extra.get("exception_type") == "ConnectionError"


def test_failed_error_string_truncated_to_500_chars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long exception messages can leak internal state (URLs with tokens,
    file paths, env content). Truncate to 500 chars before publishing to
    a public issue body. SEC-003.
    """
    long_err = "x" * 5000
    _stub_fetch_raises(monkeypatch, RuntimeError(long_err))
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{poll_pursue.sha256_hex(_BODY_A)}  2026-05-08T00:00:00Z\n")

    result = poll_pursue.poll(state)

    assert isinstance(result, poll_pursue.Failed)
    assert len(result.error) <= 500
    assert len(result.issue_body) < 1500  # body is bounded by the truncated error


def test_seeds_from_manifest_when_state_file_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the state file is missing but a manifest is reachable with an
    in-band ``csv_sha256``, seed the comparison from the manifest. This
    avoids a spurious bootstrap when the operator has run ``pursue
    scrape run`` manually but never seeded the .txt file. (vaivora P1#1)
    """
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    # state file does NOT exist
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"csv_sha256": "' + sha_a + '", "fetched_at": "2026-05-08T00:00:00Z"}\n'
    )

    result = poll_pursue.poll(state, manifest_path=manifest)

    # Manifest sha equals upstream sha => Unchanged, NOT bootstrap
    assert isinstance(result, poll_pursue.Unchanged)
    assert result.sha == sha_a


def test_state_file_takes_precedence_over_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both are present, the state file wins — it's the authoritative
    source for the workflow's bookkeeping. The manifest is only a fallback.
    """
    sha_a = poll_pursue.sha256_hex(_BODY_A)
    sha_b = poll_pursue.sha256_hex(_BODY_B)
    _stub_fetch(monkeypatch, _BODY_A)
    state = tmp_path / "data" / "last-known-csv-sha.txt"
    state.parent.mkdir(parents=True)
    state.write_text(f"{sha_a}  2026-05-08T00:00:00Z\n")
    manifest = tmp_path / "manifest.json"
    # Manifest carries a DIFFERENT sha (sha_b). State file (sha_a) wins.
    manifest.write_text(
        '{"csv_sha256": "' + sha_b + '", "fetched_at": "2026-05-08T00:00:00Z"}\n'
    )

    result = poll_pursue.poll(state, manifest_path=manifest)

    assert isinstance(result, poll_pursue.Unchanged)
    assert result.sha == sha_a
