#!/usr/bin/env python3
"""Wait for one commit's build check run to finish, and require it to succeed.

The post-deploy verify must look at THIS commit's deployment, not whatever was
live before it. The host's build reports as a check run on the pushed commit;
this polls ``GET /repos/{repo}/commits/{sha}/check-runs`` until the run named
exactly ``--name`` is ``completed``.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo \\
        python scripts/wait_for_check_run.py --sha <40-hex> [--timeout-secs 1200]

Exit 0 only when the run completed with conclusion ``success``. Any other
conclusion, a timeout, or no run of that name appearing is a failure: a missing
check run is never a pass. The token is read from the environment only.

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


def wait(fetch, *, sha: str, name: str, timeout_secs: float, interval_secs: float,
         sleep=time.sleep, clock=time.monotonic, repo_path: str = "") -> tuple[bool, str]:
    """Poll until the named run completes. Returns ``(ok, message)``."""
    deadline = clock() + timeout_secs
    last = f"no check run named {name!r} on {sha}"
    while True:
        try:
            matches = [r for r in _list_runs(fetch, repo_path, sha) if r.get("name") == name]
            if matches:
                run = max(matches, key=lambda r: r.get("id", 0))  # newest rerun wins
                if run.get("status") == "completed":
                    if run.get("conclusion") == "success":
                        return True, f"{name!r} completed successfully on {sha}"
                    return False, f"{name!r} on {sha} completed with conclusion {run.get('conclusion')!r}"
                last = f"{name!r} on {sha} is {run.get('status')!r}"
            else:
                last = f"no check run named {name!r} on {sha}"
        except Exception as exc:  # transient API/network error: keep polling until the deadline
            last = f"check-runs request failed: {exc}"
        if clock() >= deadline:
            return False, f"timed out after {timeout_secs:g}s waiting for {name!r}: {last}"
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
    ap.add_argument("--name", default=DEFAULT_NAME)
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
    ok, msg = wait(_fetcher(token), sha=args.sha, name=args.name, timeout_secs=args.timeout_secs,
                   interval_secs=args.interval_secs, repo_path=f"/repos/{repo}")
    print(msg, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
