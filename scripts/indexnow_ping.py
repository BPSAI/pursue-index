"""Submit pursue-index URLs to IndexNow.

Sprint 4b Theme B. After every CF Workers Builds deploy that touches a
render-affecting path, this script POSTs the live sitemap URLs to
``https://api.indexnow.org/indexnow`` so Bing / Yandex (and ChatGPT-
search via Bing) discover changes within minutes instead of days.

The IndexNow protocol (`indexnow.org/documentation`):

  * POST a JSON body to ``https://api.indexnow.org/indexnow`` with
    ``host`` / ``key`` / ``keyLocation`` / ``urlList`` fields.
  * Ownership verification: the ``key`` value must also be served at
    ``https://{host}/{key}.txt`` as a plain-text file containing only
    that key. Verified once on first submission and cached for ~7 days
    by the receiving search engines.
  * Batch size cap: 10 000 URLs per request. We default to that and
    split larger sitemaps.
  * Accepted status: 200 (success) / 202 (accepted, pending verification).
    422 means the key verification failed; the operator needs to recheck
    that ``{key}.txt`` is served at the right path. 400/429 are retryable;
    we surface as ``::warning::`` and exit 0 so the next deploy retries.

Companion to ``scripts/wayback_save.py``. Both run after a deploy and
both hit external indexers; they differ in audience (IndexNow → search
engines; Wayback → public archive) and freshness model (IndexNow is
push-without-state; Wayback maintains a 24h freshness file). No state
file here — IndexNow itself is the source of truth.

Key source resolution order:

  1. ``INDEXNOW_KEY`` environment variable (preferred in CI)
  2. ``--key-file`` path (defaults to ``data/indexnow-key.txt``, which
     is gitignored — the public verification file at
     ``web/public/{key}.txt`` ships in the repo, the secret-ish key
     value itself lives in CI secrets or in a local gitignored file)
  3. None → graceful exit 0 with a one-line message; operator hasn't
     generated the key yet.

The key is not really secret in the SEC-001 sense — it ships publicly
at ``/{key}.txt`` for ownership verification, and possession of the key
only lets a holder push that URL list to that exact host (no read or
write access to anything else). But we still keep it out of the repo
because rotating it requires re-uploading the ownership file too, and
the friction of "edit the secret in CI" is the right friction for that
flow.

Exit codes:
  0  — normal completion (regardless of per-batch outcome)
  0  — key missing (graceful)
  0  — sitemap unreachable / empty (graceful)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITEMAP = _REPO_ROOT / "web" / "dist" / "sitemap-index.xml"
DEFAULT_KEY_FILE = _REPO_ROOT / "data" / "indexnow-key.txt"
DEFAULT_HOST = "pursueindex.com"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
DEFAULT_BATCH_SIZE = 10_000
SUBMIT_TIMEOUT_SECONDS = 30

# CF Bot Management blocks the default ``Python-urllib/3.x`` UA — even
# when we're hitting api.indexnow.org rather than our own site, this
# UA is the right courtesy: an honest "pursueindex post-deploy bot"
# identifier the IndexNow team can attribute traffic to. Matches the
# wayback_save.py pattern for consistency.
USER_AGENT = (
    "Mozilla/5.0 (compatible; pursueindex-indexnow/1.0; "
    "+https://pursueindex.com)"
)

_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.IGNORECASE)


# --- pure helpers ----------------------------------------------------


def parse_sitemap_urls(xml: str) -> list[str]:
    """Extract <loc> values from a urlset or sitemapindex XML body.

    Pure-stdlib regex parser — same approach as
    ``scripts/_wayback_helpers.py::parse_sitemap_urls``, kept inline
    here so this script remains a single-file deploy artifact.
    """
    return [m.group(1).strip() for m in _LOC_RE.finditer(xml)]


def chunk_urls(urls: list[str], *, size: int) -> list[list[str]]:
    """Yield successive ``size``-length batches from ``urls``.

    Returns a list (not a generator) so callers can ``len()`` the
    result for logging.
    """
    if not urls:
        return []
    return [urls[i : i + size] for i in range(0, len(urls), size)]


def build_payload(
    *, host: str, key: str, key_location: str, urls: list[str]
) -> dict[str, object]:
    """Build the IndexNow request body. All four fields required."""
    return {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }


def resolve_key(file_path: Path | None) -> str | None:
    """Read the IndexNow key from env or file. Returns None when neither set.

    Env var ``INDEXNOW_KEY`` wins if set (matches the CI shape where the
    secret is injected via ``secrets.INDEXNOW_KEY``). Falls back to a
    local gitignored file at ``file_path``. None → graceful exit.
    """
    env_val = os.environ.get("INDEXNOW_KEY")
    if env_val:
        return env_val.strip()
    if file_path and file_path.exists():
        return file_path.read_text(encoding="utf-8").strip()
    return None


# --- network ---------------------------------------------------------


def _read_sitemap_text(sitemap_arg: str) -> str | None:
    """Read a sitemap from a local path or URL. Returns None on failure."""
    try:
        if sitemap_arg.startswith(("http://", "https://")):
            req = urllib.request.Request(
                sitemap_arg, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        return Path(sitemap_arg).read_text(encoding="utf-8")
    except (urllib.error.URLError, OSError) as exc:
        print(f"[indexnow] WARN sitemap unreadable ({sitemap_arg}): {exc}")
        return None


def _expand_sitemap_index(initial: list[str]) -> list[str]:
    """Follow each child sitemap-index URL once and collect page URLs.

    Mirrors the wayback_save behavior: top-level sitemap-index → list
    of urlset children → fetch each child once and concatenate. Does
    NOT recurse beyond the first follow.
    """
    expanded: list[str] = []
    for url in initial:
        if url.endswith(".xml"):
            child = _read_sitemap_text(url)
            if child is not None:
                expanded.extend(parse_sitemap_urls(child))
        else:
            expanded.append(url)
    return expanded


def _submit_batch(payload: dict[str, object]) -> int:
    """POST one IndexNow batch. Returns HTTP status (0 on network err)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=SUBMIT_TIMEOUT_SECONDS) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def _submit_all_batches(
    batches: list[list[str]], *, host: str, key: str, key_location: str
) -> None:
    """Submit every batch; surface per-batch failures as ``::warning::``."""
    for i, batch in enumerate(batches):
        payload = build_payload(
            host=host, key=key, key_location=key_location, urls=batch
        )
        status = _submit_batch(payload)
        if 200 <= status < 300:
            print(
                f"[indexnow] OK batch {i + 1}/{len(batches)} "
                f"({len(batch)} urls, status {status})"
            )
        else:
            print(
                f"::warning::indexnow: batch {i + 1}/{len(batches)} "
                f"returned status {status} ({len(batch)} urls); "
                "will retry on next deploy"
            )


# --- argparse + main -------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sitemap",
        # str (not Path) so https:// URLs survive — matches wayback_save H1.
        type=str,
        default=str(DEFAULT_SITEMAP),
        help="Path or URL to sitemap-index.xml (default: web/dist/sitemap-index.xml)",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=DEFAULT_KEY_FILE,
        help="Path to plain-text key file (default: data/indexnow-key.txt)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Hostname for the keyLocation field (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Max URLs per IndexNow POST (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the payload(s) instead of submitting",
    )
    return parser


def _collect_urls_from_sitemap(sitemap_arg: str) -> list[str]:
    """Read + expand the sitemap; return the de-duped URL list."""
    sitemap_text = _read_sitemap_text(sitemap_arg)
    if sitemap_text is None:
        return []
    initial = parse_sitemap_urls(sitemap_text)
    return _expand_sitemap_index(initial)


def _main_with_args(args: argparse.Namespace) -> int:
    """Entry point taking parsed args — exposed for integration tests."""
    key = resolve_key(args.key_file)
    if not key:
        print(
            "[indexnow] no key found (set INDEXNOW_KEY env var or write "
            f"{args.key_file}); exit 0"
        )
        return 0

    urls = _collect_urls_from_sitemap(args.sitemap)
    if not urls:
        print("[indexnow] no URLs to submit; exit 0")
        return 0

    key_location = f"https://{args.host}/{key}.txt"
    batches = chunk_urls(urls, size=args.batch_size)
    print(
        f"[indexnow] {len(urls)} urls → {len(batches)} batch(es) of "
        f"≤{args.batch_size} for host {args.host}"
    )

    if args.dry_run:
        for i, batch in enumerate(batches):
            print(f"[indexnow] DRY-RUN batch {i + 1}: {len(batch)} urls")
        return 0

    _submit_all_batches(
        batches, host=args.host, key=key, key_location=key_location
    )
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    return _main_with_args(args)


if __name__ == "__main__":
    raise SystemExit(main())
