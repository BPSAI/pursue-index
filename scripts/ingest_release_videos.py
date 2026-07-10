"""Release-aware ingest for DVIDS-hosted video/audio assets.

VID and AUD cards have ``asset_url=None`` — war.gov never surfaces direct
links, so the bytes live on DVIDS and the operator's local downloads ARE
the canonical bytes. This script maps each release's A/V cards to the
operator's downloaded ``.mp4`` files (by DOD asset id), then stages each
to NAS + uploads to R2 (content-addressed ``archive/<sha>.mp4`` +
``<card_id>.mp4`` current-pointer) and appends a registry row.

Originally a one-shot for tranche-2 (2026-05-22, VID-only); generalized to
any release via ``--release-date`` / ``--desktop`` and to include AUD.
Selection + DOD-id file matching live in ``_video_ingest_core`` (unit
tested, network-free); this file is the network + R2/NAS orchestration.

Idempotent — HEAD-checks R2 + dedupes the registry before each upload.

Run from repo root, e.g. for Release 3:
    python scripts/ingest_release_videos.py \
        --release-date 6/12/26 \
        --desktop ~/Desktop/uap_videos_061226/AARO061226 \
        --env ../pursue-opsec-staging/.env \
        --source-label "war.gov/release_03 (DVIDS videos+audio)"

Then run ``scripts/registry_root.py`` to refresh the Merkle root and
``scripts/build_video_posters.py`` for poster frames.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Helpers live in a sibling module to keep this file under arch-check limits.
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from _ingest_tranche2_helpers import (  # noqa: E402
    already_archived_card_ids,
    append_registry,
    build_registry_entry,
    ensure_src_on_path,
    make_r2_client,
    push_to_r2,
    r2_head_size,
    read_env_file,
    sha256_file,
    stage_to_nas,
)
from _video_ingest_core import (  # noqa: E402
    DVIDS_ASSET_TYPES,
    is_valid_card_id,
    is_valid_dvids_id,
    match_cards_to_files,
    select_av_cards,
)

ensure_src_on_path(_REPO_ROOT)
from build_video_posters import (  # noqa: E402
    USER_AGENT,
    extract_dod_filename,
    scrape_dod_filename,
)

from pursue_index.scrape.manifest import load_manifest  # noqa: E402

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_ENV = _REPO_ROOT / ".env"
DEFAULT_NAS = Path("/mnt/nas/personal/pursue/r2-mirror/archive")
DEFAULT_BUCKET = "pursue-pdfs"
DEFAULT_SOURCE_LABEL = "war.gov (DVIDS videos+audio)"

# Cap the DVIDS page read so a spoofed/oversized response can't exhaust memory
# (an HTML page is well under this). PR #90 review P1.
_MAX_DVIDS_BYTES = 8 * 1024 * 1024


def _fetch_dvids(url: str, timeout: float = 20.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(_MAX_DVIDS_BYTES).decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[ingest] dvids fetch fail {url}: {exc}")
        return None


def resolve_dod_filename(card: Any) -> str | None:
    """Resolve a card's ``dvids_video_id`` to its ``DOD_<id>.mp4`` filename.

    DVIDS serves most assets under ``/video/``; audio-only items can live
    under ``/audio/``. Try the video page first (covers VID + most AUD),
    then fall back to the audio page so AUD cards still resolve.
    """
    if not is_valid_dvids_id(card.dvids_video_id):
        print(f"[ingest] {card.card_id}: invalid dvids_video_id; skip")
        return None
    fn = scrape_dod_filename(card.dvids_video_id)
    if fn:
        return fn
    body = _fetch_dvids(f"https://www.dvidshub.net/audio/{card.dvids_video_id}")
    if not body:
        return None
    return extract_dod_filename(body)


def ingest_one(
    card: Any,
    local_path: Path,
    *,
    client: Any,
    bucket: str,
    nas_dir: Path,
    registry_path: Path,
    source_label: str,
    skip_card_ids: set[str],
) -> str:
    """Return one of: 'skipped', 'uploaded', 'failed'."""
    card_id = card.card_id
    if not is_valid_card_id(card_id):
        # card_id becomes an R2/NAS object key; reject anything but lowercase hex
        # so a malformed manifest value can't write to an unintended key/path.
        print(f"[ingest] {card_id!r}: invalid card_id (not hex); fail")
        return "failed"
    if card_id in skip_card_ids:
        print(f"[ingest] {card_id}: already in registry; skip")
        return "skipped"

    current_key = f"{card_id}.mp4"
    existing_size = r2_head_size(client, bucket, current_key)
    sha, size = sha256_file(local_path)
    archive_key = f"archive/{sha}.mp4"

    if existing_size == size:
        print(
            f"[ingest] {card_id}: R2 already has {current_key} "
            f"({size} B); skipping upload, recording registry row"
        )
    else:
        nas_target = stage_to_nas(local_path, sha, size, nas_dir)
        if not push_to_r2(
            client, bucket, nas_target, archive_key, current_key, size, card_id
        ):
            return "failed"

    entry = build_registry_entry(
        card, local_path, sha, size, archive_key, current_key, source_label
    )
    append_registry(registry_path, entry)
    print(
        f"[ingest] {card_id}: archived sha={sha[:12]} size={size} "
        f"current={current_key}"
    )
    return "uploaded"


def _run_ingest_loop(
    matched: dict[str, tuple[Any, Path]],
    client: Any,
    args: argparse.Namespace,
    skip: set[str],
) -> dict[str, int]:
    counts = {"uploaded": 0, "skipped": 0, "failed": 0}
    for cid in sorted(matched.keys()):
        card, fpath = matched[cid]
        result = ingest_one(
            card,
            fpath,
            client=client,
            bucket=args.bucket,
            nas_dir=args.nas,
            registry_path=args.registry,
            source_label=args.source_label,
            skip_card_ids=skip,
        )
        counts[result] += 1
    return counts


def _print_dry_run(
    matched: dict[str, tuple[Any, Path]],
    unmatched_cards: list[str],
    unmatched_files: list[Path],
) -> int:
    print("[ingest] DRY-RUN; not uploading.")
    for cid, (_card, fpath) in sorted(matched.items()):
        print(f"  {cid}  <-  {fpath.name}")
    if unmatched_cards:
        print("  unmatched cards:")
        for cid in unmatched_cards:
            print(f"    {cid}")
    if unmatched_files:
        print("  unmatched files:")
        for p in unmatched_files:
            print(f"    {p.name}")
    return 0


def _print_summary(
    counts: dict[str, int],
    unmatched_cards: list[str],
    unmatched_files: list[Path],
) -> None:
    print(
        f"[ingest] done: uploaded={counts['uploaded']} "
        f"skipped={counts['skipped']} failed={counts['failed']} "
        f"unmatched_cards={len(unmatched_cards)} "
        f"unmatched_files={len(unmatched_files)}"
    )
    if unmatched_files:
        print("[ingest] UNMATCHED FILES (no manifest card via DVIDS scrape):")
        for p in unmatched_files:
            print(f"  {p.name}")
    if unmatched_cards:
        print("[ingest] UNMATCHED CARDS (DVIDS page had no DOD file in desktop):")
        for cid in unmatched_cards:
            print(f"  {cid}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--desktop", type=Path, required=True)
    parser.add_argument("--nas", type=Path, default=DEFAULT_NAS)
    parser.add_argument("--bucket", type=str, default=DEFAULT_BUCKET)
    parser.add_argument("--source-label", default=DEFAULT_SOURCE_LABEL)
    parser.add_argument(
        "--release-date", required=True, help="Manifest release_date to ingest."
    )
    parser.add_argument(
        "--asset-types",
        default=",".join(DVIDS_ASSET_TYPES),
        help="Comma-separated asset types to ingest (default VID,AUD).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute mapping; do not upload."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = read_env_file(args.env)
    asset_types = tuple(t.strip() for t in args.asset_types.split(",") if t.strip())
    manifest = load_manifest(args.manifest)
    cards = select_av_cards(manifest.cards, args.release_date, asset_types)
    print(f"[ingest] {args.release_date} A/V cards ({asset_types}): {len(cards)}")
    desktop_mp4s = sorted(args.desktop.glob("*.mp4"))
    print(f"[ingest] desktop MP4s: {len(desktop_mp4s)}")

    matched, unmatched_cards, unmatched_files = match_cards_to_files(
        cards, desktop_mp4s, resolve_dod_filename
    )
    print(
        f"[ingest] mapping: {len(matched)} matched / "
        f"{len(unmatched_cards)} cards-without-file / "
        f"{len(unmatched_files)} files-without-card"
    )

    if args.dry_run:
        return _print_dry_run(matched, unmatched_cards, unmatched_files)

    client = make_r2_client(env)
    skip = already_archived_card_ids(args.registry)
    print(f"[ingest] registry has {len(skip)} existing card_ids with mp4 rows")
    counts = _run_ingest_loop(matched, client, args, skip)
    _print_summary(counts, unmatched_cards, unmatched_files)
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
