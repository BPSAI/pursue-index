"""Content-addressed asset archive to Cloudflare R2.

Triggered by the auto-poll workflow on detected upstream CSV change.
For every card in the new manifest with an ``asset_url``, this script:

  1. HEADs the URL to get current content-length / ETag.
  2. Compares against the most recent registry row for that
     ``card_id``. Only a HEAD whose length AND ETag both equal that row's
     skips the GET, and the card is then counted ``head-unchanged
     (unverified)``: a HEAD never certifies bytes. A changed or missing
     length or ETag, or a HEAD error, fetches and hashes the card.
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

``--full-hash`` mode (the weekly verify) skips the HEAD shortcut: every
published asset (PDF, IMG, VID, AUD) is fetched and hashed. It requires
``--max-bytes-per-run``; exceeding the budget fails the run non-zero and
names how many cards were left unhashed, never a partial run with a green
exit. A completed run appends one record to ``full-hash-runs.jsonl`` (next
to the registry, or ``--run-record``); an incomplete run writes none.

Failure modes:

  * Missing R2 credentials → exit non-zero with a clear message, in every
    mode, unless ``--dry-run`` is given.
  * Per-card fetch failures → log the URL + error, continue to the
    next card. The registry only records successful archives.
  * Same byte sha already in archive → idempotent: still upload to
    ``<card_id>.<ext>`` (current pointer) but skip the archive PUT.

Bandwidth note: first run is ~5 GB total across the referenced assets.
Subsequent runs HEAD first and re-GET only cards whose HEAD differs from
the last registry entry; ``--full-hash`` re-GETs everything.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# Make src/ importable when invoked as ``python scripts/r2_archive_assets.py``.
from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from _r2_archive_put import put_archive_and_current
from curl_cffi import requests as cffi_requests

from pursue_index.byte_dispositions import (
    RESAVE_CONTENT_VERIFIED,
    ByteDispositionError,
    load_byte_change_dispositions,
)
from pursue_index.card_id import require_card_id
from pursue_index.scrape.manifest import load_manifest

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_DISPOSITIONS = _REPO_ROOT / "data" / "byte-change-dispositions.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"
RUN_RECORD_NAME = "full-hash-runs.jsonl"
RUN_RECORD_SCHEMA = "pursue-full-hash-run/v1"
# Every asset type the registry tracks.
ASSET_TYPES = ("PDF", "IMG", "VID", "AUD")


@dataclass
class RunState:
    """Per-run tallies shared by ``_process_card`` and ``main``."""

    full_hash: bool = False
    bytes_hashed: int = 0
    # (card_id, old_sha, new_sha) for each card that already had registry rows
    # and now has a row with different bytes.
    drift: list[tuple[str, str, str]] = field(default_factory=list)


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
    every subsequent run.
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


def _last_known_size(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return None
    return rows[-1].get("byte_size")


def _head_identical(rows: list[dict[str, Any]], cl: int | None, etag: str | None) -> bool:
    """True only when HEAD reports a size and an ETag that both equal the last row's."""
    return (
        bool(rows)
        and cl is not None
        and etag is not None
        and cl == _last_known_size(rows)
        and etag == _last_known_etag(rows)
    )


def _last_known_etag(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return rows[-1].get("upstream_etag")


# Allowlisted asset extensions and the Content-Type stored for each.
# asset_filename comes from the upstream CSV, so both the key suffix and
# the stored Content-Type are taken from this map, never derived from
# the raw filename. A filename whose extension is not listed here is
# refused rather than archived under a guessed key or type.
_EXT_CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "mp4": "video/mp4",
    "m4v": "video/x-m4v",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
}


def _build_keys(card: Any, byte_sha: str) -> tuple[str, str, str]:
    """Return (archive_key, current_key, content_type) for a card's bytes.

    Raises ``ValueError`` when the card_id is not a well-formed corpus id
    or the filename's extension is not in ``_EXT_CONTENT_TYPES``.
    """
    card_id = require_card_id(card.card_id)
    ext = Path(card.asset_filename or "").suffix.lstrip(".").lower()
    content_type = _EXT_CONTENT_TYPES.get(ext)
    if content_type is None:
        raise ValueError(
            f"unsupported asset extension {ext[:16]!r} for card {card_id}"
        )
    archive_key = f"archive/{byte_sha}.{ext}"
    current_key = f"{card_id}.{ext}"
    return archive_key, current_key, content_type


def _process_card(
    card: Any,
    registry: dict[str, list[dict[str, Any]]],
    client: Any,
    bucket: str,
    dry_run: bool,
    registry_path: Path,
    state: RunState | None = None,
) -> str:
    """Return 'new' | 'unchanged' | 'archive-hit' | 'head-unchanged' | 'fail'.

    ``unchanged`` means the bytes were fetched, hashed and matched a prior row.
    ``head-unchanged`` means HEAD matched and nothing was hashed (unverified).
    """
    state = state or RunState()
    # Validate id and extension before any network or storage call; the
    # sha placeholder is replaced once the real bytes are hashed.
    try:
        _build_keys(card, "0" * 64)
    except ValueError as exc:
        print(f"[r2-archive] refused {str(card.card_id)[:40]!r}: {exc}")
        return "fail"

    rows = registry.get(card.card_id, [])
    cl, etag = head_asset(card.asset_url)
    # A HEAD answer is never proof of unchanged bytes. Only a HEAD that agrees
    # with the last row on both size and ETag is trusted to skip the fetch, and
    # then the card is reported as unverified, not unchanged. A missing size, a
    # missing ETag, a changed value or a HEAD error all fetch and hash.
    if not state.full_hash and _head_identical(rows, cl, etag):
        return "head-unchanged"

    try:
        body = fetch_asset(card.asset_url)
    except Exception as exc:
        print(f"[r2-archive] fetch fail {card.card_id}: {exc}")
        return "fail"

    state.bytes_hashed += len(body)
    byte_sha = hashlib.sha256(body).hexdigest()
    # Already saw these exact bytes for this card_id — no upload needed.
    if any(r.get("byte_sha256") == byte_sha for r in rows):
        return "unchanged"

    archive_key, current_key, content_type = _build_keys(card, byte_sha)

    archive_hit = False
    if not dry_run:
        archive_hit = put_archive_and_current(
            client, bucket, archive_key, current_key, body, content_type
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
    if rows:
        state.drift.append((card.card_id, rows[-1].get("byte_sha256", ""), byte_sha))
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
    # a high-blast-radius footgun.
    append_registry(registry_path, entry)
    label = "archive-hit" if archive_hit else "new"
    print(
        f"[r2-archive] {label}: {entry['card_id']} -> "
        f"{entry['byte_sha256'][:12]} ({entry['byte_size']} B)"
    )
    return label


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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
    parser.add_argument(
        "--full-hash",
        action="store_true",
        help="Fetch and hash every published asset, whatever HEAD reports. "
        "Requires --max-bytes-per-run.",
    )
    parser.add_argument(
        "--max-bytes-per-run",
        type=int,
        default=None,
        help="Byte budget for --full-hash. Exceeding it fails the run, naming "
        "the cards left unhashed.",
    )
    parser.add_argument(
        "--run-record",
        type=Path,
        default=None,
        help=f"Where a complete --full-hash run is recorded "
        f"(default: {RUN_RECORD_NAME} beside the registry).",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Exit non-zero, after the rows are written, when a card that already "
        "had registry rows now has a different sha, unless a matching "
        "resave-content-verified disposition covers it.",
    )
    parser.add_argument("--dispositions", type=Path, default=DEFAULT_DISPOSITIONS)
    parser.add_argument(
        "--max-full-hash-age-days",
        type=int,
        default=None,
        help="Exit non-zero, after the run, when the newest complete --full-hash "
        "record is older than this many days or there is none.",
    )
    args = parser.parse_args(argv)
    if args.full_hash and not (args.max_bytes_per_run and args.max_bytes_per_run > 0):
        parser.error("--full-hash requires --max-bytes-per-run N (a positive byte count)")
    if args.max_bytes_per_run is not None and not args.full_hash:
        parser.error("--max-bytes-per-run only applies with --full-hash")
    return args


def write_run_record(path: Path, entry: dict[str, Any]) -> None:
    """Append one complete-run record (one JSON object per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dispositions = {}
    if args.fail_on_drift:
        try:
            dispositions = load_byte_change_dispositions(args.dispositions)
        except ByteDispositionError as exc:
            print(f"[r2-archive] ERROR: {exc}", file=sys.stderr)
            return 1

    manifest = load_manifest(args.manifest)
    registry = load_registry(args.registry)
    print(
        f"[r2-archive] registry has {sum(len(v) for v in registry.values())} "
        f"prior rows across {len(registry)} card_ids"
    )

    client = None if args.dry_run else make_r2_client()
    if client is None and not args.dry_run:
        # Fail closed: a run that cannot archive must not look like a pass.
        print(
            "[r2-archive] ERROR: R2 credentials are required (CF_ACCOUNT_ID, "
            "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY) and boto3 must be installed; "
            "use --dry-run to run without them.",
            file=sys.stderr,
        )
        return 1

    state = RunState(full_hash=args.full_hash)
    counts = {"new": 0, "unchanged": 0, "head-unchanged": 0, "archive-hit": 0, "fail": 0}
    in_scope = [c for c in manifest.cards if c.asset_type in ASSET_TYPES]
    eligible = [c for c in in_scope if c.asset_url]
    no_upstream_url = len(in_scope) - len(eligible)
    limited = bool(args.limit) and args.limit < len(eligible)
    if args.limit:
        eligible = eligible[: args.limit]
    print(f"[r2-archive] processing {len(eligible)} eligible cards")

    unhashed = 0
    over_budget = False
    for i, card in enumerate(eligible):
        if args.full_hash:
            expected = _last_known_size(registry.get(card.card_id, [])) or 0
            if state.bytes_hashed + expected > args.max_bytes_per_run:
                over_budget, unhashed = True, len(eligible) - i
                break
        result = _process_card(
            card, registry, client, args.bucket, args.dry_run, args.registry, state
        )
        counts[result] = counts.get(result, 0) + 1
        if args.full_hash and state.bytes_hashed > args.max_bytes_per_run:
            over_budget, unhashed = True, len(eligible) - i - 1
            break

    print(
        f"[r2-archive] done: "
        f"new={counts['new']} unchanged={counts['unchanged']} "
        f"head-unchanged (unverified)={counts['head-unchanged']} "
        f"archive-hit={counts['archive-hit']} fail={counts['fail']} "
        f"no-upstream-url={no_upstream_url}"
    )
    rc = _full_hash_outcome(args, state, counts, over_budget, unhashed, limited, eligible,
                            no_upstream_url) if args.full_hash else 0
    rc = max(rc, _drift_outcome(args, state, dispositions))
    return max(rc, _staleness_outcome(args))


def _full_hash_outcome(args, state, counts, over_budget, unhashed, limited, eligible,
                       no_upstream_url) -> int:
    """Exit code for a ``--full-hash`` run; writes the complete-run record on success."""
    if over_budget:
        print(
            f"[r2-archive] FULL-HASH FAILED: byte budget {args.max_bytes_per_run} exceeded "
            f"after {state.bytes_hashed} bytes; {unhashed} card(s) left unhashed. "
            "No complete-run record written.",
            file=sys.stderr,
        )
        return 1
    if counts["fail"] or limited:
        why = f"{counts['fail']} card(s) failed to fetch" if counts["fail"] else "--limit was set"
        print(
            f"[r2-archive] FULL-HASH INCOMPLETE: {why}. No complete-run record written.",
            file=sys.stderr,
        )
        return 1
    if not args.dry_run:
        write_run_record(
            args.run_record or args.registry.parent / RUN_RECORD_NAME,
            {
                "schema": RUN_RECORD_SCHEMA,
                "completed_at": _now_iso(),
                "cards_hashed": len(eligible),
                "bytes_hashed": state.bytes_hashed,
                "drift_count": len(state.drift),
                "no_upstream_url": no_upstream_url,
            },
        )
    return 0


def newest_complete_run(path: Path, now: datetime | None = None) -> datetime | None:
    """Newest ``completed_at`` in the run records; junk lines and future dates are ignored."""
    now = now or datetime.now(UTC)
    newest: datetime | None = None
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        try:
            when = datetime.fromisoformat(json.loads(line)["completed_at"])
        except (ValueError, KeyError, TypeError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if when > now + timedelta(minutes=5):
            continue  # a record dated in the future is not evidence of a past run
        if newest is None or when > newest:
            newest = when
    return newest


def _staleness_outcome(args) -> int:
    """1 when the weekly full-hash record is missing or older than the allowed age."""
    if args.max_full_hash_age_days is None or args.full_hash:
        return 0
    path = args.run_record or args.registry.parent / RUN_RECORD_NAME
    newest = newest_complete_run(path)
    if newest is None:
        print(
            f"[r2-archive] STALE: no complete full-hash run on record in {path}",
            file=sys.stderr,
        )
        return 1
    age = datetime.now(UTC) - newest
    if age > timedelta(days=args.max_full_hash_age_days):
        print(
            f"[r2-archive] STALE: the newest complete full-hash run finished "
            f"{newest.isoformat()}, {age.days} days ago "
            f"(more than {args.max_full_hash_age_days} days)",
            file=sys.stderr,
        )
        return 1
    return 0


def _drift_outcome(args, state, dispositions) -> int:
    """1 when ``--fail-on-drift`` and a drifted card has no covering disposition."""
    if not args.fail_on_drift:
        return 0
    uncovered = []
    for card_id, old, new in state.drift:
        disp = dispositions.get((card_id, new))
        if disp is not None and disp.disposition == RESAVE_CONTENT_VERIFIED:
            print(f"[r2-archive] drift covered by a disposition: {card_id} {old} -> {new}")
        else:
            uncovered.append((card_id, old, new))
    for card_id, old, new in uncovered:
        print(
            f"[r2-archive] BYTE DRIFT: {card_id} old sha {old} -> new sha {new} "
            "(no resave-content-verified disposition covers it)",
            file=sys.stderr,
        )
    return 1 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
