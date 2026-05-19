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


def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Invoke ``gh <args>`` and return ``(returncode, stdout, stderr)``.

    Wrapped so tests can monkeypatch the IO boundary without touching
    the orchestration logic in ``main``. stderr is surfaced so callers
    can include the gh diagnostic in ``::warning::`` annotations
    (Codex PR #67 P1).
    """
    proc = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


# Module-level indirection so tests can swap ``_run_gh`` for a fake.
_GhRunner = Callable[[list[str]], tuple[int, str, str]]


class GhCommandFailed(RuntimeError):
    """``gh`` returned a non-zero exit code.

    Distinct from ``FileNotFoundError`` so ``main()`` can surface a
    different warning (an actual API/auth failure is operationally
    different from "gh isn't installed").
    """


# ``--limit 1000`` ceiling: ~30-min poll cadence × 24h × 7d = ~336
# tranche-detected issues at the worst-case "operator AFK during upstream
# churn" scenario. 1000 covers that with margin and still fits in a
# single gh-list page (gh paginates above 1000 anyway). Below this, the
# closer would silently truncate older issues out of the match set and
# leave them open forever. (nayru/vaivora M3)
_GH_LIST_LIMIT = "1000"


def _list_open_tranche_issues(run_gh: _GhRunner) -> list[dict]:
    rc, out, err = run_gh(
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
            _GH_LIST_LIMIT,
        ]
    )
    if rc != 0:
        # Codex P1: don't mask gh failures as no-match. Auth errors,
        # rate limits, transient 5xx, etc. need to be visible to
        # operators or stale issues accumulate silently. nayru H2:
        # include BOTH rc and stderr — they're independent diagnostic
        # facts (rc-only failures with empty stderr happen on network
        # drops; stderr-rich failures still need rc for grep-ability).
        raise GhCommandFailed(f"rc={rc}: {err.strip() or '(no stderr)'}")
    if not out.strip():
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
    promoted_sha: str,
    run_gh: _GhRunner,
) -> bool:
    """Comment on the issue, then close it. Returns True only when
    BOTH commands succeed.

    Codex P2: previously the rc of either call was ignored and
    ``main()`` always reported success — a real failure produced a
    misleading ``::notice::closed`` log line. If the comment fails we
    do NOT proceed to close (the operator-facing announcement is part
    of the contract; orphaning the close is worse than leaving the
    issue open one more day).

    nayru M4: warning messages name the tranche short-sha so a
    multi-match failure log surfaces which tranche each failure
    belongs to without forcing the operator to cross-reference issue
    number → body manually.
    """
    short = promoted_sha[:12]
    rc_c, _, err_c = run_gh(["issue", "comment", str(number), "--body", comment])
    if rc_c != 0:
        print(
            f"::warning::gh issue comment #{number} (tranche `{short}`) failed"
            f" (rc={rc_c}): {err_c.strip()}"
        )
        return False
    rc_x, _, err_x = run_gh(["issue", "close", str(number)])
    if rc_x != 0:
        print(
            f"::warning::gh issue close #{number} (tranche `{short}`) failed"
            f" (rc={rc_x}): {err_x.strip()}"
        )
        return False
    return True


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


def _close_matches(
    *,
    matches: list[dict],
    promoted_sha: str,
    comment: str,
    run_gh: _GhRunner,
) -> None:
    """Comment + close every matching issue, emitting ``::notice::`` on
    success and ``::warning::`` on per-call failure. Extracted from
    ``main()`` to keep that function under the 50-line architecture
    ceiling (nayru/arch-check H1).
    """
    short = promoted_sha[:12]
    for issue in matches:
        number = issue.get("number")
        if not isinstance(number, int):
            # nayru M5: gh's JSON schema isn't pinned; log if a future
            # response shape ever serializes issue numbers as strings.
            print(f"::warning::skipping issue with non-int number: {number!r}")
            continue
        try:
            closed = _close_with_comment(
                number=number,
                comment=comment,
                promoted_sha=promoted_sha,
                run_gh=run_gh,
            )
        except FileNotFoundError:
            # gh disappeared mid-run (extremely unusual). Log + bail
            # without raising — partial progress is fine; remaining
            # issues will close on the next promote.
            print("::warning::gh CLI disappeared mid-run; bailing")
            return
        # Codex P2: only announce the close when both gh calls
        # succeeded. ``_close_with_comment`` has already emitted a
        # ``::warning::`` for the specific subcommand that failed.
        if closed:
            print(f"::notice::closed #{number} for tranche `{short}`")


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
    except GhCommandFailed as exc:
        # Codex P1: distinguish a real gh failure (auth, rate limit,
        # transient API blip) from a legitimate no-match. Surface as a
        # warning so the operator can investigate; never fail the
        # workflow.
        print(f"::warning::gh issue list failed; skipping auto-close: {exc}")
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
    _close_matches(
        matches=matches, promoted_sha=promoted, comment=comment, run_gh=_run_gh
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
