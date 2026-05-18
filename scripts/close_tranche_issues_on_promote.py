"""Auto-close ``tranche-detected`` GitHub issues after a manifest promote.

When ``data/manifests/latest.json`` advances on the main branch, the
companion workflow ``close-tranche-on-promote.yml`` invokes this
script. It reads the ``csv_sha256`` of the promoted manifest, lists
open ``tranche-detected`` issues, matches each issue's body against
the promoted sha, and comments + closes the match(es).

Why a separate script (not extended ``pursue ingest run``):

* The trigger that defines "promoted" is the bytes landing on main,
  not the local CLI invocation. A workflow on push-to-main is the
  authoritative integration point.
* The companion workflow uses ``GITHUB_TOKEN`` with ``issues: write``,
  so we don't depend on the operator's local ``gh`` auth or any
  ``repo:write`` PAT being present in the operator's shell.
* Matches the existing companion-workflow pattern
  (``wayback-after-deploy.yml``, ``indexnow-after-deploy.yml``,
  ``cf-managed-bots-drift.yml``).

Branches:

* match found      -> comment + close, exit 0
* no match         -> ``::notice::``, exit 0 (benign on bootstrap or
                      a manual promote that doesn't correspond to an
                      open issue)
* missing manifest -> ``::warning::``, exit 0 (workflow path filter
                      should make this unreachable; defense in depth)
* corrupt manifest -> ``::warning::``, exit 0
* ``gh`` absent    -> ``::warning::``, exit 0 (lets the script run
                      locally for testing without failing the workflow)

Every branch exits 0. A parser hiccup must never fail the promote
workflow — at worst, an issue stays open until the next promote, and
the operator can close it manually.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Body line shape emitted by ``scripts/_poll_gh_io.py::changed_issue_body``:
#   * new_sha: `<64-hex>`
# Lock to lowercase 64-hex inside backticks so a future format drift
# (e.g. dropped backticks) fails closed instead of fuzzy-matching the
# wrong issue.
_NEW_SHA_RE = re.compile(r"^\*\s+new_sha:\s+`([0-9a-f]{64})`", re.MULTILINE)


def read_promoted_sha(manifest_path: Path) -> str | None:
    """Return the ``csv_sha256`` from the manifest, or None if anything
    looks off. Pure: no exceptions escape."""
    try:
        text = manifest_path.read_text()
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    sha = data.get("csv_sha256") if isinstance(data, dict) else None
    return sha if isinstance(sha, str) else None


def parse_new_sha_from_body(body: str) -> str | None:
    """Extract the first ``new_sha`` from a ``tranche-detected`` issue body.

    Returns None when the canonical line is absent or its format has drifted
    (e.g. backticks removed). Fail-closed by design: a fuzzy match could
    close the wrong issue.
    """
    if not isinstance(body, str):
        return None
    match = _NEW_SHA_RE.search(body)
    return match.group(1) if match else None


def find_matching_issues(issues: list[dict], target_sha: str) -> list[dict]:
    """Return every issue whose body's ``new_sha`` equals ``target_sha``."""
    matches: list[dict] = []
    for issue in issues:
        body = issue.get("body", "") if isinstance(issue, dict) else ""
        if parse_new_sha_from_body(body) == target_sha:
            matches.append(issue)
    return matches


def build_comment_text(
    *, promoted_sha: str, commit_sha: str | None, repo: str | None
) -> str:
    """Operator-facing comment body for the auto-close."""
    short = promoted_sha[:12]
    lines = [
        f"Auto-closed: tranche `{short}` promoted to production"
        f" (`data/manifests/latest.json` advanced on main).",
    ]
    if commit_sha and repo:
        lines.append("")
        lines.append(f"Promotion commit: https://github.com/{repo}/commit/{commit_sha}")
    return "\n".join(lines)


def _run_gh(args: list[str]) -> tuple[int, str]:
    """Invoke ``gh <args>`` and return ``(returncode, stdout)``.

    Wrapped so tests can monkeypatch the IO boundary without touching
    the orchestration logic in ``main``.
    """
    proc = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout


# Module-level indirection so tests can swap ``_run_gh`` for a fake.
_GhRunner = Callable[[list[str]], tuple[int, str]]


def _list_open_tranche_issues(run_gh: _GhRunner) -> list[dict]:
    rc, out = run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "tranche-detected",
            "--json",
            "number,title,body",
            "--limit",
            "100",
        ]
    )
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _close_with_comment(
    *,
    number: int,
    comment: str,
    run_gh: _GhRunner,
) -> None:
    run_gh(["issue", "comment", str(number), "--body", comment])
    run_gh(["issue", "close", str(number)])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/latest.json"),
        help="Promoted manifest path (defaults to data/manifests/latest.json).",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Commit SHA to link in the comment body (defaults to $GITHUB_SHA).",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/repo for the commit link (defaults to $GITHUB_REPOSITORY).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    promoted = read_promoted_sha(args.manifest)
    if promoted is None:
        print(
            f"::warning::could not read csv_sha256 from {args.manifest};"
            " skipping auto-close"
        )
        return 0
    try:
        issues = _list_open_tranche_issues(_run_gh)
    except FileNotFoundError:
        print("::warning::gh CLI not available; skipping auto-close")
        return 0
    matches = find_matching_issues(issues, promoted)
    if not matches:
        short = promoted[:12]
        print(
            f"::notice::no open tranche-detected issue matches promoted sha"
            f" `{short}`; nothing to close"
        )
        return 0
    comment = build_comment_text(
        promoted_sha=promoted, commit_sha=args.commit_sha, repo=args.repo
    )
    for issue in matches:
        number = issue.get("number")
        if not isinstance(number, int):
            continue
        try:
            _close_with_comment(number=number, comment=comment, run_gh=_run_gh)
        except FileNotFoundError:
            # gh disappeared mid-run (extremely unusual). Log + bail
            # without raising — partial progress is fine; remaining
            # issues will close on the next promote.
            print("::warning::gh CLI disappeared mid-run; bailing")
            return 0
        short = promoted[:12]
        print(f"::notice::closed #{number} for tranche `{short}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
