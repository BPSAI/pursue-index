"""Tests for the post-promote tranche-issue auto-closer.

After `pursue ingest run` promotes a tranche manifest to
``data/manifests/latest.json`` and the result lands on main, the
companion workflow ``close-tranche-on-promote.yml`` invokes this
script to comment on + close any open ``tranche-detected`` issue
whose ``new_sha`` matches the promoted ``csv_sha256``.

These tests pin:

* Pure helpers (manifest reader, body parser, matcher, comment text).
* Main-entry behavior under each branch the workflow can encounter
  (happy path, no match, missing manifest, corrupt manifest, ``gh``
  not installed) — every branch must exit 0 so a parser hiccup never
  fails the promote workflow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import close_tranche_issues_on_promote as ctc  # noqa: E402


# ----------------------------- read_promoted_sha -----------------------------


def test_read_promoted_sha_returns_csv_sha256(tmp_path: Path) -> None:
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"csv_sha256": "abc123" * 10 + "abcd"}))
    assert ctc.read_promoted_sha(manifest) == "abc123" * 10 + "abcd"


def test_read_promoted_sha_returns_none_when_missing_file(tmp_path: Path) -> None:
    assert ctc.read_promoted_sha(tmp_path / "nope.json") is None


def test_read_promoted_sha_returns_none_on_corrupt_json(tmp_path: Path) -> None:
    manifest = tmp_path / "latest.json"
    manifest.write_text("{not-json")
    assert ctc.read_promoted_sha(manifest) is None


def test_read_promoted_sha_returns_none_when_key_absent(tmp_path: Path) -> None:
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"other": "field"}))
    assert ctc.read_promoted_sha(manifest) is None


def test_read_promoted_sha_returns_none_when_key_not_string(tmp_path: Path) -> None:
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"csv_sha256": 12345}))
    assert ctc.read_promoted_sha(manifest) is None


# --------------------------- parse_new_sha_from_body -------------------------


def test_parse_new_sha_extracts_from_standard_body() -> None:
    body = (
        "Upstream PURSUE CSV changed. The operator should run the heavy"
        " ingest pipeline (`pursue scrape run` -> download -> ocr -> embed).\n\n"
        "* old_sha: `4a35f5596951aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n"
        "* new_sha: `c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`\n"
        "* observed_at: 2026-05-15T20:00:00Z\n"
    )
    assert (
        ctc.parse_new_sha_from_body(body)
        == "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    )


def test_parse_new_sha_returns_none_when_line_absent() -> None:
    body = "Some random text without the marker."
    assert ctc.parse_new_sha_from_body(body) is None


def test_parse_new_sha_returns_none_when_format_drifts() -> None:
    # If a future schema change drops the backticks, we fail closed
    # rather than fuzzy-matching and risking the wrong issue.
    body = "* new_sha: c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    assert ctc.parse_new_sha_from_body(body) is None


def test_parse_new_sha_picks_first_when_body_has_two() -> None:
    # Defensive: if a future schema change ever adds a second line that
    # also begins with ``* new_sha:`` (e.g. amended body, follow-up
    # edit), the parser takes the first one — the canonical
    # announcement is always the first matching line in the body.
    # Both candidate lines start with ``* new_sha:`` so the
    # test legitimately exercises first-match ordering, not just the
    # ``^`` anchor.
    body = (
        "* new_sha: `aaaa1111000000000000000000000000000000000000000000000000000000aa`\n"
        "* new_sha: `bbbb22220000000000000000000000000000000000000000000000000000bbbb`\n"
    )
    assert (
        ctc.parse_new_sha_from_body(body)
        == "aaaa1111000000000000000000000000000000000000000000000000000000aa"
    )


def test_parse_new_sha_round_trips_changed_issue_body() -> None:
    """Lock the producer/consumer contract end-to-end.

    ``scripts/_poll_gh_io.changed_issue_body`` is the canonical emitter
    for ``tranche-detected`` issue bodies. The closer's parser must be
    able to recover ``new_sha`` from whatever shape that function
    emits. A test that exercises both modules together prevents a silent
    body-format drift on the producer side from breaking the closer.
    """
    import importlib

    poll_gh_io = importlib.import_module("_poll_gh_io")
    new_sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    body = poll_gh_io.changed_issue_body(
        old_sha="4a35f5596951aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        new_sha=new_sha,
        ts="2026-05-15T20:00:00Z",
        bootstrap=False,
    )
    assert ctc.parse_new_sha_from_body(body) == new_sha
    # And the bootstrap path emits the same shape (worth pinning so a
    # future schema change to the bootstrap body doesn't slip past).
    bootstrap_body = poll_gh_io.changed_issue_body(
        old_sha="",
        new_sha=new_sha,
        ts="2026-05-15T20:00:00Z",
        bootstrap=True,
    )
    assert ctc.parse_new_sha_from_body(bootstrap_body) == new_sha


# ----------------------------- find_matching_issues --------------------------


def _issue(number: int, body: str) -> dict:
    return {"number": number, "title": "PURSUE tranche detected", "body": body}


def test_find_matching_issues_empty_list_returns_empty() -> None:
    assert ctc.find_matching_issues([], "abc") == []


def test_find_matching_issues_finds_single_match() -> None:
    target = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    other = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    issues = [
        _issue(63, f"* new_sha: `{other}`"),
        _issue(64, f"* new_sha: `{target}`"),
    ]
    matches = ctc.find_matching_issues(issues, target)
    assert [i["number"] for i in matches] == [64]


def test_find_matching_issues_returns_all_with_same_sha() -> None:
    # Defensive: if the poll workflow ever races and opens two issues
    # for the same new_sha, we close both.
    target = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    issues = [
        _issue(70, f"* new_sha: `{target}`"),
        _issue(71, f"* new_sha: `{target}`"),
    ]
    matches = ctc.find_matching_issues(issues, target)
    assert sorted(i["number"] for i in matches) == [70, 71]


def test_find_matching_issues_no_match_returns_empty() -> None:
    target = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    other = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    issues = [_issue(80, f"* new_sha: `{other}`")]
    assert ctc.find_matching_issues(issues, target) == []


# ------------------------------- build_comment_text --------------------------


def test_build_comment_text_with_commit_sha_includes_link() -> None:
    text = ctc.build_comment_text(
        promoted_sha="c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        commit_sha="503927d1234567890abcdef0123456789abcdef0",
        repo="BPSAI/pursue-index",
    )
    assert "c9cc83fcaf43" in text
    assert "503927d1234567890abcdef0123456789abcdef0" in text
    assert "BPSAI/pursue-index" in text
    assert "auto-closed" in text.lower()


def test_build_comment_text_without_commit_sha_omits_link() -> None:
    text = ctc.build_comment_text(
        promoted_sha="c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        commit_sha=None,
        repo=None,
    )
    assert "c9cc83fcaf43" in text
    # No commit link in the body when commit unknown.
    assert "https://" not in text
    assert "auto-closed" in text.lower()


# --------------------------------- main() integration ------------------------


def _write_manifest(path: Path, sha: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"csv_sha256": sha}))
    return path


class _FakeGh:
    """Stand-in for the subprocess.run(gh, ...) wrapper.

    Captures commands the script invokes so tests can assert on them.
    Returns issue payloads via the ``list_response`` constructor arg.
    Per-subcommand rc + stderr knobs let tests simulate gh failures
    (auth error, rate limit, transient API blip).
    """

    def __init__(
        self,
        list_response: list[dict] | None = None,
        list_raises: BaseException | None = None,
        list_rc: int = 0,
        list_stderr: str = "",
        comment_rc: int = 0,
        comment_stderr: str = "",
        close_rc: int = 0,
        close_stderr: str = "",
    ) -> None:
        self._list_response = list_response or []
        self._list_raises = list_raises
        self._list_rc = list_rc
        self._list_stderr = list_stderr
        self._comment_rc = comment_rc
        self._comment_stderr = comment_stderr
        self._close_rc = close_rc
        self._close_stderr = close_stderr
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        # Subcommand dispatch follows the gh CLI shape:
        #   gh issue list --state open --label tranche-detected --json ...
        #   gh issue comment <N> --body ...
        #   gh issue close <N>
        if self._list_raises is not None and args[:2] == ["issue", "list"]:
            raise self._list_raises
        if args[:2] == ["issue", "list"]:
            if self._list_rc != 0:
                return self._list_rc, "", self._list_stderr
            return 0, json.dumps(self._list_response), ""
        if args[:2] == ["issue", "comment"]:
            return self._comment_rc, "", self._comment_stderr
        if args[:2] == ["issue", "close"]:
            return self._close_rc, "", self._close_stderr
        return 1, "", f"unknown subcommand: {args}"


def test_main_closes_matching_issue_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_response=[_issue(64, f"* new_sha: `{sha}`")])
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(
        ["--manifest", str(manifest), "--commit-sha", "abc123", "--repo", "BPSAI/pursue-index"]
    )
    assert exit_code == 0
    # Asserts the commenting + closing path actually ran on #64.
    comment_call = next(c for c in fake.calls if c[:2] == ["issue", "comment"])
    close_call = next(c for c in fake.calls if c[:2] == ["issue", "close"])
    assert comment_call[2] == "64"
    assert close_call[2] == "64"


def test_main_no_match_exits_zero_with_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    other = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_response=[_issue(99, f"* new_sha: `{other}`")])
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    # No comment / close calls when no match.
    assert not any(c[:2] == ["issue", "comment"] for c in fake.calls)
    assert not any(c[:2] == ["issue", "close"] for c in fake.calls)
    out = capsys.readouterr().out
    assert "::notice::" in out


def test_main_missing_manifest_exits_zero_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    fake = _FakeGh()
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(tmp_path / "nope.json")])
    assert exit_code == 0
    # We never even hit gh when the manifest is missing.
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "::warning::" in out


def test_main_corrupt_manifest_exits_zero_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    manifest = tmp_path / "data/manifests/latest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{not-json")
    fake = _FakeGh()
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "::warning::" in out


def test_main_gh_not_installed_exits_zero_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_raises=FileNotFoundError("gh: command not found"))
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::warning::" in out


def test_main_closes_multiple_matching_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(
        list_response=[
            _issue(70, f"* new_sha: `{sha}`"),
            _issue(71, f"* new_sha: `{sha}`"),
        ]
    )
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    closed = sorted(c[2] for c in fake.calls if c[:2] == ["issue", "close"])
    assert closed == ["70", "71"]


# ----------------- surface gh failures --------------------------------------


def test_main_gh_list_nonzero_emits_warning_and_skips_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A non-zero rc from `gh issue list` (auth, rate limit, API blip)
    must surface as ``::warning::`` so operators notice — not be silently
    indistinguishable from a legitimate no-match.

    Assert BOTH the operator-readable stderr text AND the rc
    reach the warning — these are independent diagnostic facts and a
    future refactor that drops either would still pass without these
    pins.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_rc=1, list_stderr="gh: HTTP 401: Bad credentials")
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "gh issue list" in out
    # Operator-readable diagnostic must survive into the log line.
    assert "401" in out
    assert "Bad credentials" in out
    # And the rc must, too, so grep-able failure modes stay distinct.
    assert "rc=1" in out
    # Must not pretend it tried to close anything.
    assert "::notice::closed" not in out
    assert not any(c[:2] == ["issue", "close"] for c in fake.calls)


def test_main_gh_list_nonzero_with_empty_stderr_still_includes_rc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """rc-only failures (network drop with no stderr text)
    must still produce a usable warning. Without the rc, the operator
    has nothing to grep on.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_rc=128, list_stderr="")
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "rc=128" in out
    # No-stderr marker is present so a reader knows stderr was empty
    # (not "the script forgot to surface stderr").
    assert "(no stderr)" in out


def test_main_gh_close_nonzero_emits_warning_not_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """When `gh issue close` returns non-zero (the comment succeeded
    but the close didn't, e.g. lost a race), we must NOT emit
    ``::notice::closed`` — that would lie about the state. Emit a
    ``::warning::`` instead.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(
        list_response=[_issue(64, f"* new_sha: `{sha}`")],
        close_rc=1,
        close_stderr="gh: HTTP 422: already closed",
    )
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "close" in out
    # stderr text reaches the warning so the operator can
    # tell "already closed" (benign race) apart from real auth/perm
    # failures without re-running the workflow.
    assert "422" in out
    assert "already closed" in out
    # tranche short-sha is included so multi-match failure
    # logs are self-describing.
    assert sha[:12] in out
    # We never tell the operator the issue was closed when it wasn't.
    assert "::notice::closed" not in out


def test_main_gh_comment_failure_skips_close_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """(contributor case): when `gh issue comment` fails, we should
    NOT proceed to close the issue (that would orphan the close
    without the announcement). We also must NOT emit
    ``::notice::closed``.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(
        list_response=[_issue(64, f"* new_sha: `{sha}`")],
        comment_rc=1,
        comment_stderr="gh: HTTP 403: Resource not accessible by integration",
    )
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "comment" in out
    # stderr text + tranche short-sha both surface.
    assert "403" in out
    assert "Resource not accessible" in out
    assert sha[:12] in out
    # Critical: don't issue close if comment failed.
    assert not any(c[:2] == ["issue", "close"] for c in fake.calls)
    assert "::notice::closed" not in out


def test_main_gh_list_unbounded_stderr_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Per SEC-003: bound the size of gh stderr
    surfaced in ``::warning::`` annotations to 500 chars (plus the
    explicit ``...[truncated]`` marker). Defangs the surface where a
    gh hint line could echo a bearer-token fragment on auth failure
    and prevents rate-limit storms from blowing up the annotation log.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(list_rc=1, list_stderr="A" * 2000)
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    # The full 2000-char stderr must NOT appear verbatim.
    assert "A" * 2000 not in out
    # Truncation marker must be present.
    assert "...[truncated]" in out
    # The whole warning line must stay under the truncation ceiling
    # plus a small fixed overhead for the rc=N: prefix + marker.
    warning_lines = [line for line in out.splitlines() if "::warning::" in line]
    assert warning_lines, "expected at least one ::warning:: line"
    for line in warning_lines:
        assert len(line) < 700, f"warning line too long: {len(line)} chars"


def test_main_gh_close_unbounded_stderr_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Same truncation applies to per-issue close
    failures, not just the list-level path.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    fake = _FakeGh(
        list_response=[_issue(64, f"* new_sha: `{sha}`")],
        close_rc=1,
        close_stderr="B" * 2000,
    )
    monkeypatch.setattr(ctc, "_run_gh", fake)
    ctc.main(["--manifest", str(manifest)])
    out = capsys.readouterr().out
    assert "B" * 2000 not in out
    assert "...[truncated]" in out


def test_main_logs_warning_for_non_int_issue_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """gh's JSON schema isn't pinned. If a future response
    shape ever serializes issue numbers as strings, the closer must
    emit a ``::warning::`` rather than silently leaving the issue
    open.
    """
    sha = "c9cc83fcaf43bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    manifest = _write_manifest(tmp_path / "data/manifests/latest.json", sha)
    # Issue with number-as-string instead of int.
    fake = _FakeGh(
        list_response=[{"number": "64", "title": "x", "body": f"* new_sha: `{sha}`"}]
    )
    monkeypatch.setattr(ctc, "_run_gh", fake)
    exit_code = ctc.main(["--manifest", str(manifest)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "non-int" in out
    # The close call must not have been attempted with a stringy number.
    assert not any(c[:2] == ["issue", "close"] for c in fake.calls)
