"""Content-addressed asset archive to Cloudflare R2.

Triggered by the auto-poll workflow on detected upstream CSV change.
For every card in the new manifest with an ``asset_url``, this script:

  1. HEADs the URL to get current content-length / ETag.
  2. Compares against the most recent registry row for that
     ``card_id`` — skip when both length and ETag (if available)
     match a prior recording.
  3. Otherwise GETs the bytes via the same curl_cffi Chrome-TLS
     impersonation path the CSV fetcher uses (war.gov sits behind
     Akamai for PDFs too).
  4. Computes ``sha256`` over the bytes.
  5. PUTs the bytes to BOTH:

       ``archive/<sha256>.<ext>``       — append-only, content-addressed
       ``<card_id>.<ext>``              — current-version serving path
                                          (worker/pdf.js continues to
                                          read this exact key)

  6. Appends one row to ``data/asset-bytes-registry.jsonl`` with the
     full provenance tuple (card_id, asset_url, byte_sha256,
     byte_size, archive_key, current_key, fetched_at).

What this defeats (operator-stated 2026-05-11): "decent attempt to
defeat scrapers by keeping the same file name but serving other
content." A silent same-URL-different-bytes overlay can't fool the
archive because we content-address by BYTES, not by URL. If
upstream replaces the file at the same URL with content of equal
length and similar shape, byte_sha256 changes, the new version
lands at a new archive/<sha> key, and the registry now carries two
rows for that card_id — the diff is queryable from the JSONL
without re-fetching anything.

Failure modes (all graceful — never abort the workflow):

  * Missing R2 credentials → log a single line and exit 0; operator
    adds the secrets, the next poll picks them up.
  * Per-card fetch failures → log the URL + error, continue to the
    next card. The registry only records successful archives.
  * Same byte sha already in archive → idempotent: still upload to
    ``<card_id>.<ext>`` (current pointer) but skip the archive PUT.

Bandwidth note: first run is ~5 GB total across the ~130 referenced
assets. Subsequent runs HEAD first and re-GET only when the content
length differs from the last registry entry — typical poll-driven
runs touch only the small handful of cards that changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make src/ importable when invoked as ``python scripts/r2_archive_assets.py``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from curl_cffi import requests as cffi_requests  # noqa: E402

from pursue_index.scrape.manifest import load_manifest  # noqa: E402

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def head_asset(url: Any) -> tuple[int | None, str | None]:
    """Return (content_length, etag) or (None, None) on failure.

    Used as a cheap pre-flight check — skip the full GET when the
    length matches our last registry entry for this card_id. ``url``
    may be a pydantic ``HttpUrl`` or a plain string; we coerce to str
    so curl_cffi gets a regular string.
    """
    try:
        resp = cffi_requests.head(str(url), impersonate="chrome", timeout=30)
        if resp.status_code >= 400:
            return None, None
        cl = resp.headers.get("content-length")
        etag = resp.headers.get("etag")
        return (int(cl) if cl else None, etag)
    except Exception:
        return None, None


def fetch_asset(url: Any) -> bytes:
    """Full GET via curl_cffi Chrome impersonation. ``url`` coerces to str."""
    resp = cffi_requests.get(str(url), impersonate="chrome", timeout=300)
    resp.raise_for_status()
    return resp.content


def load_registry(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Return ``{card_id: [row, row, ...]}`` sorted newest-last by fetched_at.

    Robust against malformed rows: a line missing ``card_id`` or
    failing JSON parse is skipped, not raised. The registry is
    append-only + content-addressed and is committed by multiple
    workflows; a single corrupt mid-write line shouldn't take down
    every subsequent run (nayru P0).
    """
    if not path.exists():
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    with path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            card_id = row.get("card_id")
            if not card_id:
                continue
            out.setdefault(card_id, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: r.get("fetched_at", ""))
    return out


def append_registry(path: Path, entry: dict[str, Any]) -> None:
    """Append one JSONL row to the asset-bytes registry.

    Contract pin: every row MUST be on a single line. The workflow's
    "count new rows" step uses `grep -c '^+{'` on the diff to report
    how many rows landed in a given commit; that grep relies on each
    row starting with `{` and ending with `}\n` — i.e., no pretty-
    printed multi-line JSON. ``json.dumps`` with default settings
    enforces this (no indent argument supplied), but the contract is
    load-bearing for the workflow's row-count source, so this comment
    serves as the regression alert: do NOT add `indent=` here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        # json.dumps default: compact, no indent → single-line per row.
        fh.write(json.dumps(entry) + "\n")


def make_r2_client():
    """boto3 client for R2's S3-compatible endpoint, or None on no creds."""
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError:
        print("[r2-archive] boto3 not installed", file=sys.stderr)
        return None
    # GH Actions secrets use CF_ACCOUNT_ID (per the workflow's env
    # block); operator's local .env uses PURSUE_CF_ACCOUNT_ID (existing
    # naming convention for project-scoped env vars). Accept either so
    # the same script works in both contexts without renaming a
    # production secret.
    aid = os.environ.get("CF_ACCOUNT_ID") or os.environ.get(
        "PURSUE_CF_ACCOUNT_ID"
    )
    akid = os.environ.get("R2_ACCESS_KEY_ID")
    sak = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (aid and akid and sak):
        print(
            "[r2-archive] credentials not set; "
            "need CF_ACCOUNT_ID + R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY"
        )
        return None
    return boto3.client(
        "s3",
        endpoint_url=f"https://{aid}.r2.cloudflarestorage.com",
        aws_access_key_id=akid,
        aws_secret_access_key=sak,
        region_name="auto",
    )


def r2_head_exists(client, bucket: str, key: str) -> bool:
    """head_object → bool; False on 404 only, other errors raise."""
    try:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def _last_known_size(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    return rows[-1].get("byte_size")


def _last_known_etag(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return rows[-1].get("upstream_etag")


def _process_card(
    card: Any,
    registry: dict[str, list[dict[str, Any]]],
    client: Any,
    bucket: str,
    dry_run: bool,
    registry_path: Path,
) -> str:
    """Return 'new' | 'unchanged' | 'archive-hit' | 'fail'."""
    rows = registry.get(card.card_id, [])
    cl, etag = head_asset(card.asset_url)
    if (
        cl is not None
        and cl == _last_known_size(rows)
        and (etag is None or etag == _last_known_etag(rows))
    ):
        return "unchanged"

    try:
        body = fetch_asset(card.asset_url)
    except Exception as exc:
        print(f"[r2-archive] fetch fail {card.card_id}: {exc}")
        return "fail"

    byte_sha = hashlib.sha256(body).hexdigest()
    # Already saw these exact bytes for this card_id — no upload needed.
    if any(r.get("byte_sha256") == byte_sha for r in rows):
        return "unchanged"

    # Allowlist extensions before building R2 keys (laverna SEC-003):
    # asset_filename comes from the upstream CSV, not the operator —
    # a crafted upstream filename could otherwise inject characters
    # that R2 interprets as path separators (slashes via Path.suffix
    # on a weirdly-shaped value) or produce keys that overwrite
    # adjacent archive objects. Anything outside the allowlist falls
    # back to "pdf" — there are no non-PDF/non-image assets in the
    # corpus at the time of writing, and an unrecognized extension
    # is signal enough to warrant operator review rather than silent
    # archival under an arbitrary key.
    _ALLOWED_EXTS = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"}
    raw_ext = Path(card.asset_filename or "").suffix.lstrip(".").lower()
    ext = raw_ext if raw_ext in _ALLOWED_EXTS else "pdf"
    archive_key = f"archive/{byte_sha}.{ext}"
    current_key = f"{card.card_id}.{ext}"
    content_type = (
        mimetypes.guess_type(card.asset_filename or "")[0]
        or "application/octet-stream"
    )

    archive_hit = False
    if not dry_run:
        # Some other card may already have archived these exact bytes
        # (cross-card duplicates are rare but possible — content-addressed
        # storage handles them automatically).
        if r2_head_exists(client, bucket, archive_key):
            archive_hit = True
        else:
            client.put_object(
                Bucket=bucket,
                Key=archive_key,
                Body=body,
                ContentType=content_type,
            )
        # Always update the "current" pointer to the latest bytes.
        client.put_object(
            Bucket=bucket,
            Key=current_key,
            Body=body,
            ContentType=content_type,
        )

    entry = {
        "card_id": card.card_id,
        "asset_url": str(card.asset_url),
        "asset_filename": card.asset_filename,
        "byte_sha256": byte_sha,
        "byte_size": len(body),
        "upstream_etag": etag,
        "archive_key": archive_key,
        "current_key": current_key,
        "fetched_at": _now_iso(),
    }
    return _record_or_dryrun(entry, dry_run, archive_hit, registry_path)


def _record_or_dryrun(
    entry: dict[str, Any],
    dry_run: bool,
    archive_hit: bool,
    registry_path: Path,
) -> str:
    if dry_run:
        print(
            f"[r2-archive] DRY-RUN would archive "
            f"{entry['card_id']} -> {entry['byte_sha256'][:12]} "
            f"({entry['byte_size']} B)"
        )
        return "new"
    # Use the CLI-supplied registry path, not the module default —
    # tests/dev runs that pass `--registry /tmp/test.jsonl` previously
    # *read* from the test file but *wrote* to the production registry,
    # a high-blast-radius footgun (nayru P1).
    append_registry(registry_path, entry)
    label = "archive-hit" if archive_hit else "new"
    print(
        f"[r2-archive] {label}: {entry['card_id']} -> "
        f"{entry['byte_sha256'][:12]} ({entry['byte_size']} B)"
    )
    return label


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--bucket", type=str, default=DEFAULT_BUCKET)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip R2 puts and registry writes; just print what would happen.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most this many cards (testing). 0 = no limit.",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    registry = load_registry(args.registry)
    print(
        f"[r2-archive] registry has {sum(len(v) for v in registry.values())} "
        f"prior rows across {len(registry)} card_ids"
    )

    client = None if args.dry_run else make_r2_client()
    if client is None and not args.dry_run:
        # Graceful exit — workflow doesn't fail, operator gets a chance
        # to add the secrets without blocking subsequent runs.
        return 0

    counts = {"new": 0, "unchanged": 0, "archive-hit": 0, "fail": 0}
    eligible = [
        c
        for c in manifest.cards
        if c.asset_url and c.asset_type in ("PDF", "IMG")
    ]
    if args.limit:
        eligible = eligible[: args.limit]
    print(f"[r2-archive] processing {len(eligible)} eligible cards")

    for card in eligible:
        result = _process_card(
            card,
            registry,
            client,
            args.bucket,
            args.dry_run,
            args.registry,
        )
        counts[result] = counts.get(result, 0) + 1

    print(
        f"[r2-archive] done: "
        f"new={counts['new']} unchanged={counts['unchanged']} "
        f"archive-hit={counts['archive-hit']} fail={counts['fail']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
