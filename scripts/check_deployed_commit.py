#!/usr/bin/env python3
"""Confirm the live site was built from a given commit.

The build publishes ``/deploy-stamp.json`` (see ``web/scripts/write_deploy_stamp.mjs``),
whose ``commit`` is the commit the host built. This polls it, with a bound,
until it equals ``--sha``; edges can serve the previous deploy for a short time.

    python scripts/check_deployed_commit.py --sha <40-hex> [--base-url URL] [--timeout-secs 300]

Exit 0 on a match; 1 on a mismatch, a missing ``commit`` field, or an
unreachable stamp once the timeout passes; 3 when the edge refused every read
(HTTP 403), which says nothing about which commit is deployed and is reported
as "blocked by edge". Standard library only.

The request carries the same ``User-Agent`` as ``runbook_verify_deploy.py``:
the CDN refuses the default ``Python-urllib`` agent on every path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import os
import time
import urllib.error
import urllib.request

_SHA1 = re.compile(r"[0-9a-f]{40}")
STAMP = "deploy-stamp.json"
USER_AGENT = "pursue-index-runbook/1.0"
EDGE_BLOCKED = "blocked by edge"


def stamp_url(base_url: str, nonce: int) -> str:
    return f"{base_url.rstrip('/')}/{STAMP}?cb={nonce}"


def wait_for_commit(fetch, *, sha: str, timeout_secs: float, interval_secs: float,
                    base_url: str = "https://pursueindex.com",
                    sleep=time.sleep, clock=time.monotonic) -> tuple[bool, str]:
    deadline = clock() + timeout_secs
    attempt = 0
    while True:
        attempt += 1
        try:
            stamp = fetch(stamp_url(base_url, attempt))
            if not isinstance(stamp, dict):
                last = f"{STAMP} is not a JSON object"
            elif "commit" not in stamp:
                last = f"{STAMP} has no 'commit' field"
            elif stamp["commit"] == sha:
                return True, f"deployed commit {sha} matches"
            else:
                last = f"deployed commit is {stamp['commit']!r}, expected {sha}"
            edge_blocked = False
        except urllib.error.HTTPError as exc:
            edge_blocked = exc.code == 403
            last = f"could not read {STAMP}: {exc}"
        except Exception as exc:
            edge_blocked = False
            last = f"could not read {STAMP}: {exc}"
        if clock() >= deadline:
            if edge_blocked:
                return False, (f"{EDGE_BLOCKED}: every read of {STAMP} for {timeout_secs:g}s "
                               f"was refused with HTTP 403; the deployed commit is unknown, "
                               f"not wrong ({last})")
            return False, f"deployed build is not this commit after {timeout_secs:g}s: {last}"
        print(f"waiting: {last}", flush=True)
        sleep(interval_secs)


def _fetch(url: str):
    req = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True)
    ap.add_argument("--base-url", default="https://pursueindex.com")
    ap.add_argument("--timeout-secs", type=float, default=300)
    ap.add_argument("--interval-secs", type=float, default=10)
    args = ap.parse_args(argv)
    if not _SHA1.fullmatch(args.sha):
        print(f"--sha must be a 40-hex commit sha, got {args.sha!r}", file=sys.stderr)
        return 2
    ok, msg = wait_for_commit(_fetch, sha=args.sha, timeout_secs=args.timeout_secs,
                              interval_secs=args.interval_secs, base_url=args.base_url)
    print(msg, file=sys.stdout if ok else sys.stderr)
    if ok:
        return 0
    if msg.startswith(EDGE_BLOCKED):
        _write_output("edge_blocked", "true")
        return 3
    return 1


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


if __name__ == "__main__":
    sys.exit(main())
