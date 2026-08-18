"""Retroactively pin /removed preservation copies into the integrity layer.

Background — what this script exists to close:

  When PR #27 (war.gov framing-fix, ``a5c2f9e``, 2026-05-10) introduced
  self-hosted PDFs out of Cloudflare R2, the bulk-load was operator-
  driven via ``wrangler r2 object put``. Those uploads landed at
  ``<card_id>.<ext>`` keys only — no append-only ``archive/<sha>.<ext>``
  counterpart, no row in ``data/asset-bytes-registry.jsonl``.

  Three cards from that initial load were later replaced or removed
  upstream and now live under ``/removed`` on the public site:

    - 13f86e95aed52840  FBI 62-HQ-83894 Section 6 (370 MB)
    - 80e36017873c19a1  DOW-UAP-D20 Iraq 2023
    - aa3097b4c549a67a  NASC-State 1963 → 1952 file-swap

  Their bytes are still safe in R2, but they sit outside the integrity
  layer's view: the daily verify cron walks the current manifest, so
  it doesn't check them; the registry has nothing to diff against; a
  silent overwrite of one of these preservation copies would be
  undetectable from the integrity tooling. ``/removed`` only knows the
  metadata, not the byte_sha.

  This script closes that gap by, for each card in ``removed-cards.json``:

    1. HEAD ``<card_id>.<ext>`` in R2 to confirm the preservation copy
       is present.
    2. GET the bytes from R2 (not from upstream — the URL may now 404
       or serve a replacement file).
    3. Compute sha256.
    4. PUT to ``archive/<sha>.<ext>`` with ``IfNoneMatch: "*"`` so the
       append-only contract holds even if a future run recomputes the
       same byte_sha.
    5. Append a registry row carrying ``preserved: true`` so the daily
       verify cron can distinguish "manifest-current card" from
       "preservation copy" — for preserved cards, verification reads
       the byte_sha back out of R2 itself instead of HEAD'ing upstream
       (the upstream URL is, by definition, no longer authoritative).

Idempotent. Safe to re-run. Read-only against ``/removed`` data; the
only writes are R2 PUTs (append-only) and JSONL appends to the
registry.

Usage:
    python scripts/r2_pin_removed.py
    python scripts/r2_pin_removed.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Share helpers with r2_archive_assets so the registry contract + client
# wiring + ext allowlist stay in lockstep across the integrity tooling.
from r2_archive_assets import (  # noqa: E402
    append_registry,
    load_registry,
    make_r2_client,
)

DEFAULT_REMOVED = _REPO_ROOT / "web" / "public" / "data" / "removed-cards.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"

# Same allowlist as r2_archive_assets. Anything
# outside the allowlist falls back to "pdf" — see the comment in
# r2_archive_assets._process_card for the threat model.
_ALLOWED_EXTS = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ext_for(asset_filename: str | None) -> str:
    raw_ext = Path(asset_filename or "").suffix.lstrip(".").lower()
    return raw_ext if raw_ext in _ALLOWED_EXTS else "pdf"


def _r2_head_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _get_r2_bytes(client: Any, bucket: str, key: str) -> bytes:
    resp = client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _build_registry_row(
    card_id: str,
    asset_filename: str | None,
    asset_url: str | None,
    byte_sha: str,
    byte_size: int,
    archive_key: str,
    current_key: str,
) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "asset_url": asset_url,
        "asset_filename": asset_filename,
        "byte_sha256": byte_sha,
        "byte_size": byte_size,
        "archive_key": archive_key,
        "current_key": current_key,
        "fetched_at": _now_iso(),
        "preserved": True,
    }


def _put_archive_append_only(
    client: Any,
    bucket: str,
    archive_key: str,
    body: bytes,
    content_type: str,
) -> bool:
    """PUT with IfNoneMatch=*; return True if archive key already existed."""
    try:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]
    except ImportError:
        ClientError = Exception  # type: ignore[assignment,misc]

    try:
        client.put_object(
            Bucket=bucket,
            Key=archive_key,
            Body=body,
            ContentType=content_type,
            IfNoneMatch="*",
        )
        return False
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("PreconditionFailed", "412"):
            # Append-only contract held — existing bytes are what we want.
            return True
        raise


def _record_pinned_row(
    card: dict[str, Any],
    byte_sha: str,
    byte_size: int,
    archive_key: str,
    current_key: str,
    registry: dict[str, list[dict[str, Any]]],
    registry_path: Path,
) -> None:
    row = _build_registry_row(
        card_id=card["card_id"],
        asset_filename=card.get("asset_filename"),
        asset_url=card.get("asset_url"),
        byte_sha=byte_sha,
        byte_size=byte_size,
        archive_key=archive_key,
        current_key=current_key,
    )
    append_registry(registry_path, row)
    registry.setdefault(card["card_id"], []).append(row)


def pin_card(
    card_entry: dict[str, Any],
    client: Any,
    bucket: str,
    registry: dict[str, list[dict[str, Any]]],
    registry_path: Path,
    dry_run: bool,
) -> str:
    """Pin one /removed card into the integrity layer.

    Returns: ``already-pinned`` | ``missing-in-r2`` | ``would-pin`` |
    ``archive-existed`` | ``pinned``.
    """
    card = card_entry.get("card", {})
    card_id = card.get("card_id")
    if not card_id:
        return "missing-in-r2"
    if registry.get(card_id):
        return "already-pinned"

    asset_filename = card.get("asset_filename")
    ext = _ext_for(asset_filename)
    current_key = f"{card_id}.{ext}"
    if not _r2_head_exists(client, bucket, current_key):
        print(f"[r2-pin] missing-in-r2 {card_id}: no object at {current_key}")
        return "missing-in-r2"

    body = _get_r2_bytes(client, bucket, current_key)
    byte_sha = hashlib.sha256(body).hexdigest()
    archive_key = f"archive/{byte_sha}.{ext}"
    detail = f"{card_id} → {archive_key} ({len(body)} bytes, sha={byte_sha[:12]}...)"

    if dry_run:
        print(f"[r2-pin] would-pin {detail}")
        return "would-pin"

    content_type = (
        mimetypes.guess_type(asset_filename or "")[0] or "application/octet-stream"
    )
    archive_existed = _put_archive_append_only(
        client, bucket, archive_key, body, content_type
    )
    _record_pinned_row(
        card, byte_sha, len(body), archive_key, current_key, registry, registry_path
    )

    status = "archive-existed" if archive_existed else "pinned"
    print(f"[r2-pin] {status} {detail}")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--removed", type=Path, default=DEFAULT_REMOVED)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.removed.exists():
        print(f"[r2-pin] no removed-cards.json at {args.removed}; nothing to pin")
        return 0

    payload = json.loads(args.removed.read_text())
    entries = payload.get("removed", [])
    if not entries:
        print("[r2-pin] removed-cards.json has no entries; nothing to pin")
        return 0

    client = make_r2_client()
    if client is None:
        # make_r2_client already logged the specific gap.
        return 0

    registry = load_registry(args.registry)
    counts: dict[str, int] = {}
    for entry in entries:
        status = pin_card(
            card_entry=entry,
            client=client,
            bucket=args.bucket,
            registry=registry,
            registry_path=args.registry,
            dry_run=args.dry_run,
        )
        counts[status] = counts.get(status, 0) + 1

    print(f"[r2-pin] done: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
