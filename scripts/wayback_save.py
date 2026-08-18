"""Submit pursue-index URLs to the Wayback Machine.

Reads a list of URLs (sitemap-xml or CLI ``--url``) and GETs each at
``https://web.archive.org/save/<url>``. The Wayback save endpoint is
the long-standing one Brewster Kahle's project has exposed for years;
calling it strict-sequentially with a 2-second delay is the operator-
friendly rate-limit posture documented at
``https://archive.org/help/wayback_api.php``. Wayback accepts both GET
and POST against the save endpoint — we use GET because it's the
conventional shape for save-page-now and keeps the script trivially
inspectable in a browser if an operator wants to dry-run it manually.

Design constraints:

* **Strict-sequential.** Wayback rate-limits hard; concurrent saves
  produce ``429`` and (rarely) a temporary block on the source IP.
  ``--delay-seconds`` defaults to 2 s; tunable.
* **Idempotent.** A small JSON history file at
  ``data/wayback-history.json`` records the last save time per URL.
  URLs saved inside the freshness window (default 24 h) are skipped.
* **Origin-aware.** Wayback rejects 404/5xx origin URLs. By default
  the script HEADs each origin URL first and skips non-2xx/3xx URLs
  so the Wayback queue doesn't fill with dead pointers. Bypass with
  ``--skip-origin-check`` (e.g., archiving a known-removed URL).
* **No-op when no inputs.** If the sitemap has zero URLs or every URL
  is fresh, the script exits 0 with a one-line message.
* **DoS posture.** ``--max-urls`` caps the plan length (default 1000)
  so a runaway / attacker-controlled sitemap can't pin the Wayback
  queue.

The Wayback save endpoint itself returns 200 on accept; per-URL
failures (429, timeout, bot challenge, 404) are surfaced as GH Actions
``::warning::`` annotations but do **not** mark the run as failed —
exit 1 is reserved for catastrophic failure (unreadable history file
post-recovery, etc.). The next scheduled run picks the URL up again
once its freshness window expires.

This script is intentionally tiny and pure-stdlib (only ``urllib`` /
``http.client``) so it can run on the ``ubuntu-latest`` GitHub runner
without ``pip install``.

Exit codes:
  0  — normal completion, regardless of per-URL save outcome
  0  — credentials/network unavailable (graceful)
  1  — catastrophic failure (reserved; no current paths exercise it)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from _wayback_helpers import (  # noqa: E402  (local module)
    apply_max_urls_cap,
    build_save_url,
    build_plan,
    is_fresh,
    parse_sitemap_urls,
    should_skip_origin_status,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = _REPO_ROOT / "data" / "wayback-history.json"
DEFAULT_SITEMAP = _REPO_ROOT / "web" / "dist" / "sitemap-index.xml"
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_WINDOW_HOURS = 24
DEFAULT_MAX_URLS = 1000
SAVE_TIMEOUT_SECONDS = 60
ORIGIN_HEAD_TIMEOUT_SECONDS = 10

# Cloudflare's Bot Management blocks the default ``Python-urllib/3.x``
# User-Agent as a suspected scraper — even on our OWN site. The first
# real-world run of this workflow (2026-05-17 commit 21886ca) failed
# with ``HTTP Error 403: Forbidden`` on the sitemap fetch for exactly
# this reason. Mozilla-style UA with our project identifier bypasses
# the default block while still being honest about who's calling.
USER_AGENT = (
    "Mozilla/5.0 (compatible; pursueindex-wayback/1.0; "
    "+https://pursueindex.com)"
)


# --- history persistence ---------------------------------------------


def load_history(path: Path) -> dict[str, datetime]:
    """Load the wayback save history. Returns ``{}`` if missing OR corrupt.

    A crashed prior run could leave a half-written JSON file behind
    (M1 makes that path atomic, but pre-existing corrupt files still
    need to be tolerated). We emit a GH Actions ``::warning::`` so the
    operator sees the recovery and exit 0 from an empty history.
    """
    if not path.exists():
        return {}
    try:
        raw: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"::warning::wayback-save: history file at {path} is unreadable "
            f"({exc}); starting from an empty history"
        )
        return {}
    out: dict[str, datetime] = {}
    for url, iso in raw.items():
        out[url] = datetime.fromisoformat(iso)
    return out


def save_history(path: Path, history: dict[str, datetime]) -> None:
    """Persist the history as ISO-8601 strings.

    Write-temp-then-rename so a partial write can't corrupt the
    on-disk file. ``Path.replace`` is atomic on POSIX
    (and on Windows since 3.3 via ``MoveFileExW(REPLACE_EXISTING)``).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized: dict[str, str] = {
        url: ts.astimezone(UTC).isoformat() for url, ts in history.items()
    }
    body = json.dumps(serialized, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


# --- network ---------------------------------------------------------


def _submit_save(save_url: str, *, timeout: float = SAVE_TIMEOUT_SECONDS) -> int:
    """GET the Wayback save endpoint. Returns HTTP status code (0 on network err)."""
    req = urllib.request.Request(
        save_url, method="GET", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def _head_origin_status(
    url: str, *, timeout: float = ORIGIN_HEAD_TIMEOUT_SECONDS
) -> int:
    """HEAD the origin URL to determine if it's worth saving.

    Returns the integer status code, or 0 on network error. A 0 is
    treated as "skip" by callers — better to defer than to fire a
    Wayback save against a host that's currently flaky.
    """
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def _read_sitemap_text(sitemap_arg: str) -> str:
    """Read a sitemap from either a local path or an https URL.

    Sets ``USER_AGENT`` on the HTTPS branch because Cloudflare Bot
    Management blocks the default ``Python-urllib/3.x`` UA — even
    on our own pursueindex.com. Discovered 2026-05-17 when the first
    real wayback workflow run got 403'd on its own sitemap fetch.
    """
    if sitemap_arg.startswith(("http://", "https://")):
        req = urllib.request.Request(
            sitemap_arg, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    return Path(sitemap_arg).read_text()


def _expand_sitemap_index(
    initial_urls: list[str], *, sitemap_origin: str | None
) -> list[str]:
    """Expand the top-level sitemap-index by following each child once.

    Does NOT recurse — nested sub-indexes (rare; we don't emit any)
    are passed through to Wayback as-is. For Astro's 2-level sitemap
    this is correct behavior: the top-level is a sitemapindex whose
    children are urlsets, and we fetch each child once.
    """
    expanded: list[str] = []
    for url in initial_urls:
        if url.endswith(".xml") and (
            sitemap_origin is None or url.startswith(sitemap_origin)
        ):
            try:
                xml = _read_sitemap_text(url)
                expanded.extend(parse_sitemap_urls(xml))
            except (urllib.error.URLError, OSError) as exc:
                print(f"[wayback-save] WARN failed to expand {url}: {exc}")
        else:
            expanded.append(url)
    return expanded


def _collect_urls(args: argparse.Namespace) -> list[str]:
    """Resolve the source URL list from CLI args.

    ``args.sitemap`` is typed as ``str`` at the argparse layer —
    typing it as Path silently collapses ``https://``
    to ``https:/`` because ``pathlib.Path`` normalizes consecutive
    slashes. The str type keeps the URL form intact so the http branch
    of ``_read_sitemap_text`` activates.
    """
    if args.url:
        return list(args.url)
    sitemap_text = _read_sitemap_text(args.sitemap)
    initial = parse_sitemap_urls(sitemap_text)
    return _expand_sitemap_index(initial, sitemap_origin=None)


def _filter_dead_origins(
    plan: list[str], *, skip_origin_check: bool
) -> list[str]:
    """Drop URLs whose origin HEAD returns 4xx/5xx.

    Wires ``should_skip_origin_status`` into the plan so dead
    pointers never reach the Wayback queue. ``--skip-origin-check``
    bypasses this for cases where the operator wants to archive a
    known-removed URL (race: capture in Wayback before it's also
    expunged there).
    """
    if skip_origin_check:
        return plan
    keep: list[str] = []
    for url in plan:
        status = _head_origin_status(url)
        if status == 0:
            # Network error HEADing — defer rather than fire a save.
            print(
                f"::warning::wayback-save: origin HEAD failed for {url}; "
                "deferring to next run"
            )
            continue
        if should_skip_origin_status(status):
            print(
                f"::warning::wayback-save: origin status {status} for {url}; "
                "skipping Wayback save"
            )
            continue
        keep.append(url)
    return keep


def _run_plan(
    plan: list[str], *, delay_seconds: float
) -> dict[str, datetime]:
    """Submit each URL in ``plan``. Returns the new-history dict.

    Per-URL failures are surfaced as ``::warning::`` GH Actions
    annotations (so the operator sees them in the run summary) but do
    not cause exit 1 — Wayback's 429 is recoverable on the next run
    and dropping the workflow on a single throttled URL would lose
    the partial-success history. See H3.
    """
    new_history: dict[str, datetime] = {}
    for i, url in enumerate(plan):
        if i > 0:
            time.sleep(delay_seconds)
        save_url = build_save_url(url)
        status = _submit_save(save_url)
        if status == 200:
            new_history[url] = datetime.now(UTC)
            print(f"[wayback-save] OK  {url}")
        else:
            print(
                f"::warning::wayback-save: {url} returned status {status} "
                "(will retry on next scheduled run)"
            )
    return new_history


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sitemap",
        # H1: NOT Path — argparse + Path collapses https:// to https:/.
        type=str,
        default=str(DEFAULT_SITEMAP),
        help="Path or URL to sitemap-index.xml (default: web/dist/sitemap-index.xml)",
    )
    parser.add_argument(
        "--url",
        action="append",
        help="Explicit URL to save (repeatable); overrides --sitemap",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY,
        help="Path to wayback history JSON (default: data/wayback-history.json)",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help="Skip URLs saved within this many hours (default: 24)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Sleep between save calls (default: 2.0)",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=DEFAULT_MAX_URLS,
        help="Cap on plan length post-freshness (default: 1000)",
    )
    parser.add_argument(
        "--skip-origin-check",
        action="store_true",
        help="Skip the origin HEAD probe (save even 404 origins)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the save plan without submitting",
    )
    return parser


def _main_with_args(args: argparse.Namespace) -> int:
    """Entry point taking parsed args — exposed for integration tests."""
    try:
        urls = _collect_urls(args)
    except (FileNotFoundError, urllib.error.URLError) as exc:
        print(f"[wayback-save] could not read sitemap: {exc}")
        return 0

    if not urls:
        print("[wayback-save] no URLs to consider; exit 0")
        return 0

    history = load_history(args.history)
    now = datetime.now(UTC)
    window = timedelta(hours=args.window_hours)
    plan = build_plan(urls, history=history, now=now, window=window)
    plan, cap_warning = apply_max_urls_cap(plan, max_urls=args.max_urls)
    if cap_warning is not None:
        print(cap_warning)
    print(
        f"[wayback-save] {len(urls)} urls; "
        f"{len(plan)} stale (>{args.window_hours}h); "
        f"{len(urls) - len(plan)} skipped fresh or capped"
    )

    if args.dry_run:
        for url in plan:
            print(f"[wayback-save] PLAN {url}")
        return 0
    if not plan:
        return 0

    plan = _filter_dead_origins(plan, skip_origin_check=args.skip_origin_check)
    if not plan:
        save_history(args.history, history)
        return 0

    new_history = _run_plan(plan, delay_seconds=args.delay_seconds)
    history.update(new_history)
    save_history(args.history, history)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    return _main_with_args(args)


if __name__ == "__main__":
    raise SystemExit(main())
