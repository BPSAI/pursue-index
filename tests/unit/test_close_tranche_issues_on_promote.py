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
    # Defensive: the standard body only has one new_sha line, but if a
    # comment or later edit appends another, take the first (the
    # canonical announcement is the first line of the body).
    body = (
        "* new_sha: `aaaa1111000000000000000000000000000000000000000000000000000000aa`\n"
        "follow-up edit: * new_sha: `bbbb22220000000000000000000000000000000000000000000000000000bbbb`\n"
    )
    assert (
        ctc.parse_new_sha_from_body(body)
        == "aaaa1111000000000000000000000000000000000000000000000000000000aa"
    )


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
    """

    def __init__(
        self,
        list_response: list[dict] | None = None,
        list_raises: BaseException | None = None,
    ) -> None:
        self._list_response = list_response or []
        self._list_raises = list_raises
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(list(args))
        # Subcommand dispatch follows the gh CLI shape:
        #   gh issue list --state open --label tranche-detected --json ...
        #   gh issue comment <N> --body ...
        #   gh issue close <N>
        if self._list_raises is not None and args[:2] == ["issue", "list"]:
            raise self._list_raises
        if args[:2] == ["issue", "list"]:
            return 0, json.dumps(self._list_response)
        if args[:2] == ["issue", "comment"]:
            return 0, ""
        if args[:2] == ["issue", "close"]:
            return 0, ""
        return 1, f"unknown subcommand: {args}"


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
