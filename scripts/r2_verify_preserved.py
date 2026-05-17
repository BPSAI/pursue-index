"""Daily byte-verify of /removed preservation copies in R2.

Companion to ``r2_archive_assets.py``. That script walks the current
manifest and HEAD-checks upstream URLs — it's the right tool for the
silent-overlay-detected threat (upstream serves different bytes at the
same URL). It is **not** the right tool for ``/removed`` cards: their
upstream URL is, by definition, no longer authoritative (404 or
serving a replacement file), and the preservation copy lives entirely
inside our R2 bucket.

This script re-reads the preserved bytes from the immutable archive
mirror at ``archive/<byte_sha256>.<ext>`` and verifies the bytes still
hash to the pinned ``byte_sha256`` in
``data/asset-bytes-registry.jsonl``. The archive key is the structural
preservation copy: it's append-only (IfNoneMatch-guarded) and is
keyed by its own content hash, so under the project's normal
invariants this verify is tautological — but the verify exists
precisely to catch the rare failure mode where the tautology breaks
(write-key compromise, accidental ``wrangler r2 object put`` against
the archive key, ACL drift on the bucket).

The mutable current-pointer key at ``<card_id>.<ext>`` is
deliberately **not** verified here. After the 2026-05-14 Section 6
preserved-pin reaffirmation policy (commit 13f86e95aed52840),
current_key legitimately serves whatever bytes upstream is currently
publishing at the original URL — including bytes that diverge from
the preserved/pinned sha. Verifying current_key produced daily
false-positive ``preserved-tampered`` issues (Issues #61, #64 closed)
that the cron then kept re-filing. The script now verifies the
immutable archive/<sha>.<ext> preservation copy, not the mutable
current-pointer.

Exit codes:
  0  — every preserved row matches its pinned byte_sha
  0  — credentials missing (graceful, like r2_archive_assets)
  1  — at least one preserved row failed verification (mismatch or
       missing). Workflow-side step inspects stdout to decide whether
       to file a ``preserved-tampered`` issue.

Idempotent. Read-only against R2 (GET + HEAD only, no writes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from r2_archive_assets import load_registry, make_r2_client  # noqa: E402

DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"


def _latest_preserved_row(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the newest row carrying preserved=True, or None.

    ``load_registry`` sorts each card_id's rows oldest-first by
    fetched_at; we want the most recent preserved entry so a re-pin
    (operator intentional byte change) supersedes the original.
    """
    preserved_rows = [r for r in rows if r.get("preserved") is True]
    if not preserved_rows:
        return None
    return max(preserved_rows, key=lambda r: r.get("fetched_at", ""))


def _read_r2_bytes(client: Any, bucket: str, key: str) -> bytes | None:
    """GET R2 object body, or return None on 404 / NoSuchKey."""
    try:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]
    except ImportError:
        ClientError = Exception  # type: ignore[assignment,misc]

    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    body = resp["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def verify_preserved(
    registry: dict[str, list[dict[str, Any]]],
    client: Any,
    bucket: str,
) -> dict[str, list[Any]]:
    """Walk every preserved card in the registry and check R2 bytes.

    Returns: ``{"ok": [card_id,...], "mismatch": [{...},...],
    "missing": [card_id,...]}``.
    """
    ok: list[str] = []
    mismatch: list[dict[str, Any]] = []
    missing: list[str] = []

    for card_id, rows in registry.items():
        row = _latest_preserved_row(rows)
        if row is None:
            continue
        # Sprint 4a (2026-05-17): verify the immutable archive copy,
        # not the mutable current-pointer. See module docstring for
        # Section 6 reaffirmation context (Issues #61, #64).
        archive_key = row["archive_key"]
        expected_sha = row["byte_sha256"]
        body = _read_r2_bytes(client, bucket, archive_key)
        if body is None:
            missing.append(card_id)
            print(f"[verify-preserved] MISSING {card_id} key={archive_key}")
            continue
        actual_sha = hashlib.sha256(body).hexdigest()
        if actual_sha == expected_sha:
            ok.append(card_id)
        else:
            mismatch.append(
                {
                    "card_id": card_id,
                    "archive_key": archive_key,
                    "expected_sha": expected_sha,
                    "actual_sha": actual_sha,
                    "actual_size": len(body),
                }
            )
            print(
                f"[verify-preserved] MISMATCH {card_id} "
                f"expected={expected_sha[:12]}... actual={actual_sha[:12]}..."
            )

    return {"ok": ok, "mismatch": mismatch, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="optional path to write a JSON report; written even on all-ok",
    )
    args = parser.parse_args()

    client = make_r2_client()
    if client is None:
        return 0

    registry = load_registry(args.registry)
    report = verify_preserved(registry, client, args.bucket)

    summary = (
        f"[verify-preserved] done: ok={len(report['ok'])} "
        f"mismatch={len(report['mismatch'])} missing={len(report['missing'])}"
    )
    print(summary)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2))

    if report["mismatch"] or report["missing"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
