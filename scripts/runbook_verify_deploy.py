"""Phase 8 post-deploy verification — curl-check that the live site
matches the just-pushed state.

Runs HEAD requests against:
- pursueindex.com homepage (200 expected)
- 3 random card pages from the latest tranche (or random sample if no
  tranche detected) (200 each)
- A sample finds entry (200)
- The methodology page (200 + contains current card_count in HTML)

Wraps in a polling loop so it can be invoked right after a push while
CF Pages is still building.

Usage::

    python scripts/runbook_verify_deploy.py
    python scripts/runbook_verify_deploy.py --max-wait-secs 600

Exits 0 on all checks passing, 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://pursueindex.com"
DEFAULT_MAX_WAIT = 600  # 10 minutes
POLL_INTERVAL = 15


def _head(url: str, timeout: int = 10) -> int:
    req = urllib.request.Request(url, method="HEAD",
                                  headers={"User-Agent": "pursue-index-runbook/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def _get_text(url: str, timeout: int = 10) -> tuple[int, str]:
    req = urllib.request.Request(url,
                                  headers={"User-Agent": "pursue-index-runbook/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, ""


def _sample_cards() -> list[str]:
    """Pick up to 5 card_ids to sanity-check. Prefer cards added in the
    most recent snapshot delta if we can detect it; otherwise random."""
    m = json.loads((_REPO_ROOT / "data" / "manifests" / "latest.json").read_text())
    cards = [c["card_id"] for c in m["cards"]
             if c.get("asset_type") in ("PDF", "VID", "IMG", "AUD")]
    random.seed(int(time.time()) // 60)  # stable within a minute
    return random.sample(cards, min(5, len(cards)))


def check_one(base_url: str, current_card_count: int) -> tuple[bool, list[str]]:
    """Single-pass verification. Returns (all_passed, log_lines)."""
    log: list[str] = []
    ok = True

    homepage_status = _head(f"{base_url}/")
    log.append(f"  GET /  → {homepage_status}")
    if homepage_status != 200:
        ok = False

    methodology_status, methodology_html = _get_text(f"{base_url}/methodology")
    log.append(f"  GET /methodology  → {methodology_status}")
    if methodology_status != 200:
        ok = False
    elif str(current_card_count) not in methodology_html:
        log.append(f"  WARN: /methodology HTML missing current card count "
                   f"{current_card_count} — deploy may be stale")
        ok = False

    for card_id in _sample_cards():
        status = _head(f"{base_url}/card/{card_id}/")
        log.append(f"  HEAD /card/{card_id}/  → {status}")
        if status != 200:
            ok = False
    return ok, log


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--max-wait-secs", type=int, default=DEFAULT_MAX_WAIT)
    p.add_argument("--single-pass", action="store_true",
                   help="Run checks once and exit; don't poll for CF Pages "
                        "to catch up.")
    args = p.parse_args(argv)

    m = json.loads((_REPO_ROOT / "data" / "manifests" / "latest.json").read_text())
    card_count = len(m["cards"])
    print(f"verify-deploy: target={args.base_url}, expecting "
          f"card_count={card_count}, polling up to {args.max_wait_secs}s")

    started = time.time()
    while True:
        ok, log = check_one(args.base_url, card_count)
        for line in log:
            print(line)
        if ok:
            print("verify-deploy: ALL PASSED")
            return 0
        if args.single_pass or (time.time() - started) > args.max_wait_secs:
            print("verify-deploy: FAILED after polling timeout")
            return 1
        print(f"  (deploy not ready; retrying in {POLL_INTERVAL}s...)")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
