#!/usr/bin/env python3
"""Wait for one commit's build check run to finish, and require it to succeed.

The post-deploy verify must look at THIS commit's deployment, not whatever was
live before it. The host's build reports as a check run on the pushed commit;
this polls ``GET /repos/{repo}/commits/{sha}/check-runs`` until the run named
exactly ``--name`` is ``completed``.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo \\
        python scripts/wait_for_check_run.py --sha <40-hex> [--timeout-secs 1200]

Exit 0 when the run completed with conclusion ``success``, OR when the manual
fallback workflow ``deploy-cf.yml`` has a successful run for the same sha (both
are polled within one timeout). Exit 0 also, with ``superseded=true`` written to
``$GITHUB_OUTPUT``, when the build was cancelled/skipped/never appeared and
``main`` is now a descendant of the sha. A failed build is never superseded;
any other outcome or a timeout is a failure. The token is read from the environment only.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request

DEFAULT_NAME = "Workers Builds: pursue-index"
NAME_ENV = "WORKERS_BUILD_CHECK_NAME"  # the workflow sets this once; DEFAULT_NAME is the only literal
FALLBACK_WORKFLOW = "deploy-cf.yml"


def default_name() -> str:
    return os.environ.get(NAME_ENV) or DEFAULT_NAME

API = "https://api.github.com"
_SHA1 = re.compile(r"[0-9a-f]{40}")
PER_PAGE = 100
MAX_PAGES = 20


def _list_runs(fetch, repo_path: str, sha: str) -> list[dict]:
    runs: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{repo_path}/commits/{sha}/check-runs?per_page={PER_PAGE}&page={page}"
        body = fetch(url)
        batch = body.get("check_runs") or []
        runs.extend(batch)
        if not batch or len(runs) >= int(body.get("total_count", 0)):
            break
    return runs


def _fallback_runs(fetch, repo_path: str, sha: str) -> list[dict]:
    url = f"{repo_path}/actions/workflows/{FALLBACK_WORKFLOW}/runs?head_sha={sha}&per_page={PER_PAGE}"
    return fetch(url).get("workflow_runs") or []


def _is_superseded(fetch, repo_path: str, sha: str) -> bool:
    """True when ``main`` has moved strictly ahead of ``sha`` (a descendant)."""
    try:
        cmp_ = fetch(f"{repo_path}/compare/{sha}...main")
    except Exception:
        return False
    return int(cmp_.get("ahead_by", 0)) > 0 and int(cmp_.get("behind_by", 0)) == 0


def _describe_wb(name: str, sha: str, run: dict | None) -> str:
    if run is None:
        return f"no check run named {name!r} on {sha}"
    if run.get("status") != "completed":
        return f"{name!r} on {sha} is {run.get('status')!r}"
    return f"{name!r} on {sha} completed with conclusion {run.get('conclusion')!r}"


def _describe_fb(runs: list[dict]) -> str:
    if not runs:
        return "no fallback run"
    run = max(runs, key=lambda r: r.get("id", 0))
    if run.get("status") != "completed":
        return f"fallback {FALLBACK_WORKFLOW} run is {run.get('status')!r}"
    return f"fallback {FALLBACK_WORKFLOW} run completed with conclusion {run.get('conclusion')!r}"


def wait(fetch, *, sha: str, name: str, timeout_secs: float, interval_secs: float,
         sleep=time.sleep, clock=time.monotonic, repo_path: str = "") -> tuple[str, str]:
    """Poll until this commit's deploy succeeds. Returns ``(status, message)``.

    ``status`` is ``"ok"`` (Workers Builds check run succeeded, or the manual
    ``deploy-cf.yml`` fallback run succeeded), ``"superseded"`` (the build
    never ran/was cancelled/skipped and ``main`` is now a descendant of ``sha``
    -- a failed build is never superseded), or ``"fail"``.
    """
    deadline = clock() + timeout_secs
    last = f"{_describe_wb(name, sha, None)}; no fallback run"
    while True:
        try:
            matches = [r for r in _list_runs(fetch, repo_path, sha) if r.get("name") == name]
            wb = max(matches, key=lambda r: r.get("id", 0)) if matches else None  # newest rerun wins
            fb = _fallback_runs(fetch, repo_path, sha)
            if wb and wb.get("status") == "completed" and wb.get("conclusion") == "success":
                return "ok", f"{name!r} completed successfully on {sha}"
            if any(r.get("status") == "completed" and r.get("conclusion") == "success" for r in fb):
                return "ok", f"fallback {FALLBACK_WORKFLOW} run completed successfully on {sha}"
            last = f"{_describe_wb(name, sha, wb)}; {_describe_fb(fb)}"
            wb_gone = wb is None or (wb.get("status") == "completed"
                                     and wb.get("conclusion") in ("cancelled", "skipped"))
            if wb_gone and _is_superseded(fetch, repo_path, sha):
                return "superseded", (f"superseded: {last}; main is ahead of {sha}, so the newer "
                                      "commit's own verify run covers the deploy")
        except Exception as exc:  # transient API/network error: keep polling until the deadline
            last = f"request failed: {exc}"
        if clock() >= deadline:
            return "fail", f"timed out after {timeout_secs:g}s waiting for {name!r}: {last}"
        print(f"waiting: {last}", flush=True)
        sleep(interval_secs)


def _fetcher(token: str):
    def fetch(path: str) -> dict:
        req = urllib.request.Request(
            API + path,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    return fetch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True, help="commit whose build to wait for (40-hex)")
    ap.add_argument("--name", default=None, help=f"check run name (default: ${NAME_ENV} or the built-in)")
    ap.add_argument("--timeout-secs", type=float, default=1200)
    ap.add_argument("--interval-secs", type=float, default=15)
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY must be set in the environment", file=sys.stderr)
        return 2
    if not _SHA1.fullmatch(args.sha):
        print(f"--sha must be a 40-hex commit sha, got {args.sha!r}", file=sys.stderr)
        return 2
    status, msg = wait(_fetcher(token), sha=args.sha, name=args.name or default_name(),
                       timeout_secs=args.timeout_secs, interval_secs=args.interval_secs,
                       repo_path=f"/repos/{repo}")
    if status == "superseded":
        print(f"::notice title=superseded::{msg}")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as fh:
                fh.write("superseded=true\n")
        print(msg)
        return 0
    print(msg, file=sys.stdout if status == "ok" else sys.stderr)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
