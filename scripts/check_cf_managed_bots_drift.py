"""Detect drift between CF Managed robots.txt and our CF_MANAGED_BOTS const.

Cloudflare's Managed robots.txt feature prepends a Disallow block for a
known set of well-behaved-AI / training-bot user-agents to every
robots.txt CF serves under that feature. We hardcode that set in
``web/src/lib/robots.ts`` as ``CF_MANAGED_BOTS`` so the rendered
``/robots.txt`` body can filter those entries out (avoids duplicate
``User-agent:`` lines per RFC 9309, and a Lighthouse SEO warning).

If CF expands the upstream Managed list, our hardcoded constant drifts
out of sync. A drift in either direction matters:

* CF adds a bot we don't list → our body emits a duplicate that CF
  also prepends. Lighthouse SEO flag re-triggers.
* CF removes a bot we list → our body silently *omits* a Disallow that
  used to be enforced by CF Managed, opening a hole.

This script fetches the live ``https://pursueindex.com/robots.txt``,
extracts the CF-prepended UA block (between the documented sentinel
comments), and diffs against the const in ``robots.ts``. Exit 1 on
drift; emit a ``::warning::`` annotation so the weekly cron files an
issue automatically. Operator action: update CF_MANAGED_BOTS to match.

Pure-stdlib; runs on ``ubuntu-latest`` without ``pip install``.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIVE_URL = "https://pursueindex.com/robots.txt"
DEFAULT_ROBOTS_TS = _REPO_ROOT / "web" / "src" / "lib" / "robots.ts"

# Sentinel comments that bracket the CF-managed section in the live
# response. CF emits both BEGIN/END markers verbatim; we anchor on them.
CF_BEGIN_RE = re.compile(
    r"#\s*BEGIN\s+Cloudflare\s+Managed\s+content", re.IGNORECASE
)
CF_END_RE = re.compile(
    r"#\s*END\s+Cloudflare\s+Managed\s+Content", re.IGNORECASE
)
UA_RE = re.compile(r"^User-agent:\s*(\S.*?)\s*$", re.MULTILINE)

# Const-extraction regex: matches a string-array TS export of the form
# `export const CF_MANAGED_BOTS: readonly string[] = [ "...", ... ]`.
# Tolerates inline `//` and `/* */` comments (we strip them before
# parsing the array body).
CONST_RE = re.compile(
    r"export\s+const\s+CF_MANAGED_BOTS[^=]*=\s*\[(?P<body>.*?)\]\s*as\s+const",
    re.DOTALL,
)
LITERAL_RE = re.compile(r'"([^"]+)"')


def extract_cf_block(robots_txt: str) -> str:
    """Slice out the CF Managed block from a full robots.txt body.

    Returns an empty string if no BEGIN sentinel is found (caller
    treats as "CF Managed disabled" — no comparison possible).
    """
    begin = CF_BEGIN_RE.search(robots_txt)
    if begin is None:
        return ""
    end = CF_END_RE.search(robots_txt, begin.end())
    end_pos = end.start() if end else len(robots_txt)
    return robots_txt[begin.end() : end_pos]


def parse_user_agents(block: str) -> list[str]:
    """Return all ``User-agent: X`` values from a robots.txt slice.

    Ignores the wildcard ``*`` (CF emits a canonical wildcard in the
    Managed block; we don't track that in CF_MANAGED_BOTS).
    """
    out: list[str] = []
    for m in UA_RE.finditer(block):
        agent = m.group(1).strip()
        if agent == "*":
            continue
        out.append(agent)
    return out


def parse_const_list(robots_ts: str) -> list[str]:
    """Extract the literal members of ``CF_MANAGED_BOTS`` from robots.ts.

    Strips inline ``//`` line comments before pulling string literals,
    so the TS source can keep its inline annotations.
    """
    m = CONST_RE.search(robots_ts)
    if m is None:
        raise ValueError("CF_MANAGED_BOTS const not found in robots.ts")
    body = m.group("body")
    # Strip // line comments so they don't pollute the literal scan.
    body = re.sub(r"//[^\n]*", "", body)
    return list(LITERAL_RE.findall(body))


def diff_bot_lists(
    live: list[str], const: list[str]
) -> tuple[list[str], list[str]]:
    """Return ``(only_in_live, only_in_const)`` — case-insensitive.

    Cloudflare lowercases some agents (e.g. ``meta-externalagent``).
    Case-insensitive compare avoids spurious drift signal from CF's
    output style. Preserves the live spelling for the report.
    """
    live_lower = {b.lower(): b for b in live}
    const_lower = {b.lower(): b for b in const}
    only_live = [live_lower[k] for k in sorted(set(live_lower) - set(const_lower))]
    only_const = [const_lower[k] for k in sorted(set(const_lower) - set(live_lower))]
    return only_live, only_const


def fetch_robots_txt(url: str, *, timeout: float = 20.0) -> str:
    """GET the live robots.txt body."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DEFAULT_LIVE_URL,
        help="URL of the deployed robots.txt to compare against",
    )
    parser.add_argument(
        "--robots-ts",
        type=Path,
        default=DEFAULT_ROBOTS_TS,
        help="Path to web/src/lib/robots.ts",
    )
    return parser


def report_drift(only_live: list[str], only_const: list[str]) -> None:
    """Emit a ``::warning::`` annotation per drift category."""
    if only_live:
        print(
            "::warning::cf-managed-drift: bots in live CF block but NOT in "
            f"CF_MANAGED_BOTS const: {', '.join(only_live)}"
        )
    if only_const:
        print(
            "::warning::cf-managed-drift: bots in CF_MANAGED_BOTS const but "
            f"NOT in live CF block: {', '.join(only_const)}"
        )


def main() -> int:
    args = _build_parser().parse_args()
    try:
        body = fetch_robots_txt(args.url)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"::warning::cf-managed-drift: could not fetch {args.url}: {exc}")
        return 0  # soft-fail; treat fetch error as non-drift

    cf_block = extract_cf_block(body)
    if not cf_block:
        print(
            f"::warning::cf-managed-drift: no CF Managed block found in {args.url} "
            "(feature disabled? sentinel changed?). Skipping drift check."
        )
        return 0
    live_bots = parse_user_agents(cf_block)
    const_bots = parse_const_list(args.robots_ts.read_text(encoding="utf-8"))
    only_live, only_const = diff_bot_lists(live_bots, const_bots)
    if only_live or only_const:
        report_drift(only_live, only_const)
        return 1
    print(
        f"[cf-managed-drift] no drift; {len(const_bots)} bots match live CF block"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
