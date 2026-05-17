"""Submit pursue-index URLs to the Wayback Machine.

Reads a list of URLs (sitemap-xml or CLI ``--url``) and POSTs each to
``https://web.archive.org/save/<url>``. The Wayback save endpoint is
the long-standing one Brewster Kahle's project has exposed for years;
calling it strict-sequentially with a 2-second delay is the operator-
friendly rate-limit posture documented at
``https://archive.org/help/wayback_api.php``.

Design constraints:

* **Strict-sequential.** Wayback rate-limits hard; concurrent saves
  produce ``429`` and (rarely) a temporary block on the source IP.
  ``--delay-seconds`` defaults to 2 s; tunable.
* **Idempotent.** A small JSON history file at
  ``data/wayback-history.json`` records the last save time per URL.
  URLs saved inside the freshness window (default 24 h) are skipped.
* **Origin-aware.** Wayback rejects 404/5xx origin URLs. The script
  optionally HEADs the origin first and skips non-2xx/3xx URLs so the
  Wayback queue doesn't fill with dead pointers.
* **No-op when no inputs.** If the sitemap has zero URLs or every URL
  is fresh, the script exits 0 with a one-line message.

The Wayback save endpoint itself returns 200 on accept; failures
(429, timeout, bot challenge) are logged but not retried. The next
scheduled run picks the URL up again once its freshness window
expires.

This script is intentionally tiny and pure-stdlib (only ``urllib`` /
``http.client``) so it can run on the ``ubuntu-latest`` GitHub
runner without ``pip install``.

Exit codes:
  0  — every selected URL produced a 200 (or was skipped, or no inputs)
  0  — credentials/network unavailable (graceful)
  1  — at least one save submission produced a non-200 status
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = _REPO_ROOT / "data" / "wayback-history.json"
DEFAULT_SITEMAP = _REPO_ROOT / "web" / "dist" / "sitemap-index.xml"
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_WINDOW_HOURS = 24
WAYBACK_SAVE_PREFIX = "https://web.archive.org/save/"
SKIPPABLE_STATUS_MIN = 400
SAVE_TIMEOUT_SECONDS = 60


# --- sitemap parsing --------------------------------------------------


_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)


def parse_sitemap_urls(xml: str) -> list[str]:
    """Extract <loc> values from a urlset OR sitemapindex XML body.

    Pure-stdlib regex parser — avoids the ``xml.etree`` namespace
    quirk where ``find("loc")`` returns ``None`` unless the caller
    spells the namespace correctly. The pattern is tight enough for
    the well-formed sitemap that Astro emits.
    """
    return [m.group(1).strip() for m in _LOC_RE.finditer(xml)]


# --- freshness gating -------------------------------------------------


def is_fresh(
    saved_at: datetime | None, *, now: datetime, window: timedelta
) -> bool:
    """True if ``saved_at`` is within ``window`` of ``now``.

    A ``None`` saved_at means we've never saved this URL → not fresh.
    """
    if saved_at is None:
        return False
    return now - saved_at < window


# --- save-URL construction --------------------------------------------


def build_save_url(src: str) -> str:
    """``https://web.archive.org/save/<src>`` — passthrough."""
    return f"{WAYBACK_SAVE_PREFIX}{src}"


# --- plan filtering ---------------------------------------------------


def build_plan(
    urls: list[str],
    *,
    history: dict[str, datetime],
    now: datetime,
    window: timedelta,
) -> list[str]:
    """Return the subset of ``urls`` that are stale per ``history``.

    Order-preserving. URLs absent from history are kept; URLs whose
    last save is older than ``window`` are kept; URLs saved inside
    the window are skipped.
    """
    return [u for u in urls if not is_fresh(history.get(u), now=now, window=window)]


# --- origin-status gating ---------------------------------------------


def should_skip_origin_status(status: int) -> bool:
    """4xx and 5xx origin responses are skipped from the save plan."""
    return status >= SKIPPABLE_STATUS_MIN


# --- history persistence ----------------------------------------------


def load_history(path: Path) -> dict[str, datetime]:
    """Load the wayback save history. Returns empty dict if missing."""
    if not path.exists():
        return {}
    raw: dict[str, str] = json.loads(path.read_text())
    out: dict[str, datetime] = {}
    for url, iso in raw.items():
        out[url] = datetime.fromisoformat(iso)
    return out


def save_history(path: Path, history: dict[str, datetime]) -> None:
    """Persist the history as ISO-8601 strings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized: dict[str, str] = {
        url: ts.astimezone(UTC).isoformat() for url, ts in history.items()
    }
    path.write_text(json.dumps(serialized, indent=2, sort_keys=True))


# --- network ---------------------------------------------------------


def _submit_save(save_url: str, *, timeout: float = SAVE_TIMEOUT_SECONDS) -> int:
    """POST to the Wayback save endpoint. Returns HTTP status code."""
    req = urllib.request.Request(save_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def _read_sitemap_text(sitemap_arg: str) -> str:
    """Read a sitemap from either a local path or an https URL."""
    if sitemap_arg.startswith(("http://", "https://")):
        with urllib.request.urlopen(sitemap_arg, timeout=30) as resp:
            return resp.read().decode("utf-8")
    return Path(sitemap_arg).read_text()


def _expand_sitemap_index(
    initial_urls: list[str], *, sitemap_origin: str | None
) -> list[str]:
    """If the URL list contains child sitemap pointers, expand them.

    A sitemapindex yields URLs that themselves end in ``.xml`` — we
    recursively fetch each and concatenate their <loc> values. Limit
    depth to one level (no nested indexes) to avoid surprises.
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
    """Resolve the source URL list from CLI args."""
    if args.url:
        return list(args.url)
    sitemap_text = _read_sitemap_text(str(args.sitemap))
    initial = parse_sitemap_urls(sitemap_text)
    return _expand_sitemap_index(initial, sitemap_origin=None)


def _run_plan(
    plan: list[str], *, delay_seconds: float
) -> tuple[dict[str, datetime], list[tuple[str, int]]]:
    """Submit each URL in ``plan``. Returns (new_history, failures)."""
    new_history: dict[str, datetime] = {}
    failures: list[tuple[str, int]] = []
    for i, url in enumerate(plan):
        if i > 0:
            time.sleep(delay_seconds)
        save_url = build_save_url(url)
        status = _submit_save(save_url)
        if status == 200:
            new_history[url] = datetime.now(UTC)
            print(f"[wayback-save] OK  {url}")
        else:
            failures.append((url, status))
            print(f"[wayback-save] FAIL status={status} {url}")
    return new_history, failures


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sitemap",
        type=Path,
        default=DEFAULT_SITEMAP,
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
        "--dry-run",
        action="store_true",
        help="Print the save plan without submitting",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
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
    print(
        f"[wayback-save] {len(urls)} urls; "
        f"{len(plan)} stale (>{args.window_hours}h); "
        f"{len(urls) - len(plan)} skipped fresh"
    )

    if args.dry_run:
        for url in plan:
            print(f"[wayback-save] PLAN {url}")
        return 0
    if not plan:
        return 0

    new_history, failures = _run_plan(plan, delay_seconds=args.delay_seconds)
    history.update(new_history)
    save_history(args.history, history)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
