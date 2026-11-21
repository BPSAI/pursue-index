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
     Akamai for PDFs too). Every type is STREAMED: chunks feed the sha256
     and a temporary file, so no response body is ever held in memory.
  4. Computes ``sha256`` over the bytes. Equal to the card's LATEST registry
     row = unchanged. Anything else is a new row and drift, even when the
     sha equals an OLDER row (a revert to earlier bytes is a change).
  5. PUTs the file to BOTH:

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

``--fail-on-drift`` (the daily and weekly gates) reads the registry itself, not
only what the run fetched: the poll lane appends new-sha rows without that flag,
so by the next run the fetched sha equals the latest row. Every row appended
since the previous complete verify run (the newest ``drift-gate-passes.jsonl``
marker a passing gate wrote, else the newest complete ``--full-hash`` record in
``full-hash-runs.jsonl``, else the last 8 days) whose sha differs from the same
card's previous row fails the run unless a ``resave-content-verified`` disposition
covers ``(card_id, new sha)``. A card's first row is net-new, never drift.

Failure modes:

  * Missing R2 credentials → ``--full-hash`` (the weekly verify) fails closed,
    exit 1. Every other caller warns, skips the archive step and exits 0, so a
    poll tick before the secrets exist is not a failure. ``--dry-run`` needs none.
  * Per-card fetch failures → log the URL + error, continue to the
    next card. The registry only records successful archives.
  * Same byte sha already in archive → idempotent: still upload to
    ``<card_id>.<ext>`` (current pointer) but skip the archive PUT.

``--asset-types PDF,IMG`` restricts a run to those types (the poll lane uses it
to keep large VID/AUD fetches out of the 30-minute tick; the daily HEAD pass and
the weekly full hash cover all four). A filtered ``--full-hash`` is never recorded
as complete.

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
import json
import os
import tempfile
from typing import Any

# Make src/ importable when invoked as ``python scripts/r2_archive_assets.py``.
from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from _r2_archive_put import put_archive_and_current
from _r2_fetch import fetch_asset, head_asset, head_identical, last_known_size
from _r2_run_state import (
    GATE_MARKER_SCHEMA,
    RUN_RECORD_NAME,
    RunState,
    drift_outcome,
    drift_window_start,
    full_hash_outcome,
    gate_marker_path,
    now_iso,
    registry_drift_since,
    staleness_outcome,
    write_run_record,
)

from pursue_index.byte_dispositions import (
    ByteDispositionError,
    load_byte_change_dispositions,
)
from pursue_index.card_id import require_card_id
from pursue_index.scrape.manifest import load_manifest

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_DISPOSITIONS = _REPO_ROOT / "data" / "byte-change-dispositions.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"
# Every asset type the registry tracks.
ASSET_TYPES = ("PDF", "IMG", "VID", "AUD")


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

    ``unchanged`` means the bytes were fetched, hashed and equal the card's LATEST
    registry row. ``head-unchanged`` means HEAD matched and nothing was hashed
    (unverified). Bytes equal to an older row are a change, not unchanged.
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
    cl, etag, last_modified = head_asset(card.asset_url)
    # A HEAD answer is never proof of unchanged bytes. Only a HEAD that agrees
    # with the last row (size + ETag, or size + Last-Modified when there is no
    # ETag) is trusted to skip the fetch, and
    # then the card is reported as unverified, not unchanged.
    if not state.full_hash and head_identical(rows, cl, etag, last_modified):
        return "head-unchanged"

    with tempfile.TemporaryDirectory(prefix="r2-archive-") as tmp:
        body = Path(tmp) / "asset"
        try:
            byte_sha, size = fetch_asset(card.asset_url, body)
        except Exception as exc:
            print(f"[r2-archive] fetch fail {card.card_id}: {exc}")
            return "fail"
        state.bytes_hashed += size
        # Only the LATEST row decides: bytes equal to an older row are a revert.
        if rows and rows[-1].get("byte_sha256") == byte_sha:
            return "unchanged"
        fetched = (body, byte_sha, size, (etag, last_modified))
        sink = (client, bucket, dry_run, registry_path)
        return _archive_new_bytes(card, rows, fetched, sink, state)


def _archive_new_bytes(
    card: Any,
    rows: list[dict[str, Any]],
    fetched: tuple[Path, str, int, tuple[str | None, str | None]],
    sink: tuple[Any, str, bool, Path],
    state: RunState,
) -> str:
    """PUT the fetched file, append the registry row, and note drift against the latest row."""
    body, byte_sha, size, (etag, last_modified) = fetched
    client, bucket, dry_run, registry_path = sink
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
        "byte_size": size,
        "upstream_etag": etag,
        "upstream_last_modified": last_modified,
        "archive_key": archive_key,
        "current_key": current_key,
        "fetched_at": now_iso(),
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


def _core_args(parser: argparse.ArgumentParser) -> None:
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
        "--asset-types",
        type=lambda v: tuple(t.strip().upper() for t in v.split(",") if t.strip()),
        default=ASSET_TYPES,
        help=f"Comma-separated asset types to process (default: {','.join(ASSET_TYPES)}). "
        "The poll lane passes PDF,IMG.",
    )


def _verify_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--full-hash",
        action="store_true",
        help="Fetch and hash every published asset, whatever HEAD reports. "
        "Requires --max-bytes-per-run. This is the only mode that fails when R2 "
        "credentials are missing; every other mode warns, skips and exits 0.",
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
        "had registry rows now has a different sha (detected by this run, or by any "
        "lane's row appended since the previous complete run), unless a matching "
        "resave-content-verified disposition covers it.",
    )
    parser.add_argument("--dispositions", type=Path, default=DEFAULT_DISPOSITIONS)
    parser.add_argument(
        "--gate-marker",
        type=Path,
        default=None,
        help="Where a passing --fail-on-drift run is marked (default: drift-gate-passes.jsonl "
        "beside the registry). The drift gate also scans every registry row appended since "
        "the newest marker, else since the newest complete --full-hash record, else the "
        "last 8 days.",
    )
    parser.add_argument(
        "--max-full-hash-age-days",
        type=int,
        default=None,
        help="Exit non-zero, after the run, when the newest complete --full-hash "
        "record is older than this many days or there is none.",
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _core_args(parser)
    _verify_args(parser)
    args = parser.parse_args(argv)
    if args.full_hash and not (args.max_bytes_per_run and args.max_bytes_per_run > 0):
        parser.error("--full-hash requires --max-bytes-per-run N (a positive byte count)")
    if args.max_bytes_per_run is not None and not args.full_hash:
        parser.error("--max-bytes-per-run only applies with --full-hash")
    if not args.asset_types or set(args.asset_types) - set(ASSET_TYPES):
        parser.error(f"--asset-types must be a non-empty subset of {','.join(ASSET_TYPES)}")
    return args


def _no_credentials(args) -> int:
    """No R2 client: the weekly full-hash fails closed; every other caller warns and skips."""
    if args.full_hash:
        print(
            "[r2-archive] ERROR: R2 credentials are required for --full-hash (CF_ACCOUNT_ID, "
            "R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY) and boto3 must be installed; a weekly "
            "pass that cannot archive must not look like a pass.",
            file=sys.stderr,
        )
        return 1
    print(
        "[r2-archive] WARNING: R2 credentials not set (or boto3 missing); "
        "skipping the archive step.",
        file=sys.stderr,
    )
    return staleness_outcome(args)


def _select_cards(manifest, args, state: RunState) -> list[Any]:
    """The cards this run covers; records why a ``--full-hash`` run is not a complete one."""
    in_scope = [c for c in manifest.cards if c.asset_type in args.asset_types]
    eligible = [c for c in in_scope if c.asset_url]
    state.no_upstream_url = len(in_scope) - len(eligible)
    if set(args.asset_types) != set(ASSET_TYPES):
        state.partial_reason = f"--asset-types {','.join(args.asset_types)} is a subset"
    if args.limit and args.limit < len(eligible):
        state.partial_reason = "--limit was set"
    return eligible[: args.limit] if args.limit else eligible


def _run_cards(args, eligible, registry, client, state: RunState) -> None:
    """Process each card in order, stopping when the ``--full-hash`` byte budget is spent."""
    for i, card in enumerate(eligible):
        if args.full_hash:
            expected = last_known_size(registry.get(card.card_id, [])) or 0
            if state.bytes_hashed + expected > args.max_bytes_per_run:
                state.over_budget, state.unhashed = True, len(eligible) - i
                return
        result = _process_card(
            card, registry, client, args.bucket, args.dry_run, args.registry, state
        )
        state.counts[result] = state.counts.get(result, 0) + 1
        if args.full_hash and state.bytes_hashed > args.max_bytes_per_run:
            state.over_budget, state.unhashed = True, len(eligible) - i - 1
            return


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

    started = now_iso()
    since = drift_window_start(args)  # read before this run appends anything

    client = None if args.dry_run else make_r2_client()
    if client is None and not args.dry_run:
        return _no_credentials(args)

    state = RunState(full_hash=args.full_hash)
    eligible = _select_cards(manifest, args, state)
    state.cards_hashed = len(eligible)
    print(f"[r2-archive] processing {len(eligible)} eligible cards")
    _run_cards(args, eligible, registry, client, state)

    c = state.counts
    print(
        f"[r2-archive] done: "
        f"new={c['new']} unchanged={c['unchanged']} "
        f"head-unchanged (unverified)={c['head-unchanged']} "
        f"archive-hit={c['archive-hit']} fail={c['fail']} "
        f"no-upstream-url={state.no_upstream_url}"
    )
    rc = full_hash_outcome(args, state) if args.full_hash else 0
    # The registry itself, not only this run's own findings: the poll lane appends
    # new-sha rows without --fail-on-drift, so the fetched sha can equal the latest row.
    seen = registry_drift_since(load_registry(args.registry), since) if args.fail_on_drift else ()
    drift_rc = drift_outcome(args, state, dispositions, seen)
    if args.fail_on_drift and not drift_rc and not args.dry_run:
        write_run_record(
            gate_marker_path(args), {"schema": GATE_MARKER_SCHEMA, "completed_at": started}
        )
    return max(rc, drift_rc, staleness_outcome(args))


if __name__ == "__main__":
    sys.exit(main())
