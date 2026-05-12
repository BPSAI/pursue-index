"""Daily byte-verify of /removed preservation copies in R2.

Companion to ``r2_archive_assets.py``. That script walks the current
manifest and HEAD-checks upstream URLs — it's the right tool for the
silent-overlay-detected threat (upstream serves different bytes at the
same URL). It is **not** the right tool for ``/removed`` cards: their
upstream URL is, by definition, no longer authoritative (404 or
serving a replacement file), and the preservation copy lives entirely
inside our R2 bucket.

This script re-reads each preserved row from R2 itself and compares
the byte_sha256 of what's currently at ``<card_id>.<ext>`` against the
pinned sha in ``data/asset-bytes-registry.jsonl``. A mismatch here is
a different threat: **something inside our control plane changed the
preservation bytes** — a buggy script run, a leaked write key, an
accidental ``wrangler r2 object put``. The append-only
``archive/<sha>.<ext>`` mirror is protected by IfNoneMatch, but the
current-pointer key is not, and the daily manifest-walker skips
preserved cards (they're not in the manifest). Without this script,
silent tampering of a preservation copy is undetectable.

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
        current_key = row["current_key"]
        expected_sha = row["byte_sha256"]
        body = _read_r2_bytes(client, bucket, current_key)
        if body is None:
            missing.append(card_id)
            print(f"[verify-preserved] MISSING {card_id} key={current_key}")
            continue
        actual_sha = hashlib.sha256(body).hexdigest()
        if actual_sha == expected_sha:
            ok.append(card_id)
        else:
            mismatch.append(
                {
                    "card_id": card_id,
                    "current_key": current_key,
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
