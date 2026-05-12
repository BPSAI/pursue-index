"""One-shot R2 bucket reconciliation against the asset-bytes registry.

Lists every object in the `pursue-pdfs` bucket and compares against
``data/asset-bytes-registry.jsonl``. Reports:

  - **registered**: keys in both the registry and the bucket
  - **missing**: keys in the registry but NOT in the bucket (should be 0;
    means the integrity layer thinks we've archived something we haven't)
  - **orphan**: keys in the bucket but NOT in the registry (May 8-era
    manual uploads, replacement-card predecessors, anything outside the
    integrity layer's view)

Read-only against R2 (LIST + HEAD only, never DELETE / PUT). Safe to
run anytime.

Usage:
    python scripts/r2_reconcile.py
    python scripts/r2_reconcile.py --json    # machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_BUCKET = "pursue-pdfs"


def make_r2_client():
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError:
        print("[r2-reconcile] boto3 not installed", file=sys.stderr)
        return None
    aid = os.environ.get("CF_ACCOUNT_ID") or os.environ.get("PURSUE_CF_ACCOUNT_ID")
    akid = os.environ.get("R2_ACCESS_KEY_ID")
    sak = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (aid and akid and sak):
        print(
            "[r2-reconcile] missing creds — need CF_ACCOUNT_ID + "
            "R2_ACCESS_KEY_ID + R2_SECRET_ACCESS_KEY",
            file=sys.stderr,
        )
        return None
    return boto3.client(
        "s3",
        endpoint_url=f"https://{aid}.r2.cloudflarestorage.com",
        aws_access_key_id=akid,
        aws_secret_access_key=sak,
        region_name="auto",
    )


def list_bucket(client, bucket: str) -> list[dict]:
    objects: list[dict] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "MaxKeys": 1000}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []) or []:
            objects.append(
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "etag": obj.get("ETag", "").strip('"'),
                }
            )
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return objects


def load_registry(path: Path) -> tuple[set[str], set[str]]:
    """Return (archive_keys, current_keys) covered by the registry."""
    archive_keys: set[str] = set()
    current_keys: set[str] = set()
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("archive_key"):
                archive_keys.add(row["archive_key"])
            if row.get("current_key"):
                current_keys.add(row["current_key"])
    return archive_keys, current_keys


def classify(
    bucket_keys: set[str],
    registry_archive: set[str],
    registry_current: set[str],
) -> dict[str, list[str]]:
    registered_keys = registry_archive | registry_current
    return {
        "in_both": sorted(bucket_keys & registered_keys),
        "missing_from_bucket": sorted(registered_keys - bucket_keys),
        "orphan_in_bucket": sorted(bucket_keys - registered_keys),
    }


def summarize_orphans(orphans: list[str]) -> dict[str, int]:
    buckets: dict[str, int] = defaultdict(int)
    for key in orphans:
        if key.startswith("archive/"):
            buckets["archive/* (content-addressed)"] += 1
        elif "/" in key:
            buckets[f"{key.split('/', 1)[0]}/*"] += 1
        else:
            buckets["<card_id>.<ext> (current-pointer)"] += 1
    return dict(buckets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    client = make_r2_client()
    if client is None:
        return 2

    objects = list_bucket(client, args.bucket)
    bucket_keys = {o["key"] for o in objects}
    size_by_key = {o["key"]: o["size"] for o in objects}
    mtime_by_key = {o["key"]: o["last_modified"] for o in objects}

    reg_archive, reg_current = load_registry(args.registry)
    classification = classify(bucket_keys, reg_archive, reg_current)

    if args.json:
        out = {
            "bucket": args.bucket,
            "bucket_object_count": len(bucket_keys),
            "registry_archive_count": len(reg_archive),
            "registry_current_count": len(reg_current),
            "in_both": len(classification["in_both"]),
            "missing_from_bucket": classification["missing_from_bucket"],
            "orphan_in_bucket": [
                {
                    "key": k,
                    "size": size_by_key.get(k),
                    "last_modified": mtime_by_key.get(k),
                }
                for k in classification["orphan_in_bucket"]
            ],
            "orphan_summary": summarize_orphans(classification["orphan_in_bucket"]),
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"=== R2 reconciliation: bucket={args.bucket} ===")
    print(f"Bucket objects:                  {len(bucket_keys)}")
    print(f"Registry archive_keys:           {len(reg_archive)}")
    print(f"Registry current_keys:           {len(reg_current)}")
    print(f"Registered (archive + current):  {len(reg_archive | reg_current)}")
    print()
    print(f"In both bucket + registry:       {len(classification['in_both'])}")
    print(f"Missing from bucket (BAD if >0): {len(classification['missing_from_bucket'])}")
    print(f"Orphan in bucket:                {len(classification['orphan_in_bucket'])}")

    if classification["missing_from_bucket"]:
        print("\n--- MISSING FROM BUCKET ---")
        for k in classification["missing_from_bucket"]:
            print(f"  {k}")

    if classification["orphan_in_bucket"]:
        print("\n--- ORPHAN OBJECTS (in bucket, not in registry) ---")
        summary = summarize_orphans(classification["orphan_in_bucket"])
        for cat, n in summary.items():
            print(f"  {cat:40s} {n}")
        print()
        print("Per-object listing:")
        for k in classification["orphan_in_bucket"]:
            size_mb = (size_by_key.get(k) or 0) / 1_000_000
            mtime = mtime_by_key.get(k) or ""
            print(f"  {k:50s} {size_mb:9.2f} MB   {mtime}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
