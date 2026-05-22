"""Helpers for ``ingest_tranche2_videos.py`` — R2/NAS/registry plumbing.

Split out to keep the main ingest script under arch-check size limits.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_env_file(env_path: Path) -> dict[str, str]:
    """Parse ``.env`` line-by-line.

    python-dotenv chokes on malformed lines 53-57 of this project's
    ``.env`` (whitespace-prefixed "Read Only" key names). We read
    manually and only accept ``K=V`` lines whose key is a bare
    identifier — anything else is silently skipped.
    """
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum():
            continue
        out[key] = value.strip()
    return out


def make_r2_client(env: dict[str, str]) -> Any:
    import boto3  # type: ignore[import-untyped]

    aid = env.get("R2_ACCOUNT_ID")
    akid = env.get("R2_ACCESS_KEY_ID")
    sak = env.get("R2_SECRET_ACCESS_KEY")
    if not (aid and akid and sak):
        raise RuntimeError("R2 credentials missing from .env")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{aid}.r2.cloudflarestorage.com",
        aws_access_key_id=akid,
        aws_secret_access_key=sak,
        region_name="auto",
    )


def r2_head_size(client: Any, bucket: str, key: str) -> int | None:
    """Return ContentLength of ``key`` or None if missing."""
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    try:
        resp = client.head_object(Bucket=bucket, Key=key)
        return int(resp["ContentLength"])
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def upload_to_r2(client: Any, bucket: str, local_path: Path, key: str) -> None:
    client.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
    )


def append_registry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def already_archived_card_ids(registry_path: Path) -> set[str]:
    """Return the set of card_ids that already have an MP4 registry row."""
    done: set[str] = set()
    if not registry_path.exists():
        return done
    with registry_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ck = row.get("current_key", "")
            af = row.get("asset_filename", "")
            ak = row.get("archive_key", "")
            if (
                ck.endswith(".mp4")
                or af.endswith(".mp4")
                or ak.endswith(".mp4")
            ):
                done.add(row.get("card_id", ""))
    return done


def stage_to_nas(local_path: Path, sha: str, size: int, nas_dir: Path) -> Path:
    """Mirror the file to ``<NAS>/<sha>.mp4`` content-addressed."""
    nas_dir.mkdir(parents=True, exist_ok=True)
    nas_target = nas_dir / f"{sha}.mp4"
    if not nas_target.exists() or nas_target.stat().st_size != size:
        shutil.copy2(local_path, nas_target)
    return nas_target


def push_to_r2(
    client: Any,
    bucket: str,
    nas_target: Path,
    archive_key: str,
    current_key: str,
    size: int,
    card_id: str,
) -> bool:
    """Upload both R2 keys (archive + current). Return False on failure."""
    if r2_head_size(client, bucket, archive_key) != size:
        try:
            upload_to_r2(client, bucket, nas_target, archive_key)
        except Exception as exc:
            print(f"[ingest] {card_id}: archive upload FAILED: {exc}")
            return False
    try:
        upload_to_r2(client, bucket, nas_target, current_key)
    except Exception as exc:
        print(f"[ingest] {card_id}: current upload FAILED: {exc}")
        return False
    return True


def build_registry_entry(
    card: Any,
    local_path: Path,
    sha: str,
    size: int,
    archive_key: str,
    current_key: str,
    source_label: str,
) -> dict[str, Any]:
    """Construct the JSONL row for ``data/asset-bytes-registry.jsonl``."""
    dod_name = (
        local_path.name.split("video_2605_")[-1]
        if "video_2605_" in local_path.name
        else local_path.name
    )
    return {
        "card_id": card.card_id,
        "asset_url": f"https://www.dvidshub.net/video/{card.dvids_video_id}",
        "asset_filename": local_path.name,
        "byte_sha256": sha,
        "byte_size": size,
        "upstream_etag": None,
        "archive_key": archive_key,
        "current_key": current_key,
        "fetched_at": now_iso(),
        "source": source_label,
        "dvids_video_id": str(card.dvids_video_id),
        "dod_asset_filename": dod_name,
    }


def ensure_src_on_path(repo_root: Path) -> None:
    src = repo_root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    scripts_dir = repo_root / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
