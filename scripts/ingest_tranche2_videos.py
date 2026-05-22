"""One-shot ingest for tranche-2 DOD MP4s (2026-05-22).

Operator placed 57 MP4 files in ``~/Desktop/uap052226/``. The tranche-2
VID cards in the manifest have ``asset_url=None`` (war.gov never
surfaced direct video links for the May 22 release), so the operator's
local files ARE the canonical bytes.

This script:

  1. Scrapes every tranche-2 VID card's DVIDS page to discover its
     ``DOD_<id>.mp4`` filename (reuses the same helper from
     ``build_video_posters.py``).
  2. Matches each desktop MP4 against a card by ``DOD_<id>.mp4``.
  3. For each matched card:
       a. Computes sha256 + byte_size.
       b. HEADs ``<card_id>.mp4`` in R2; SKIPs if size already matches.
       c. Copies to NAS at ``<NAS>/archive/<sha>.mp4`` (idempotent).
       d. Uploads to R2 at ``archive/<sha>.mp4`` (immutable, content-
          addressed) AND ``<card_id>.mp4`` (current-pointer).
       e. Appends one row to ``data/asset-bytes-registry.jsonl``.
  4. Reports unmatched desktop files and unmatched manifest cards.

Idempotent — re-runs HEAD-check before each upload and registry append.

Run from repo root:
    python scripts/ingest_tranche2_videos.py

Then run ``scripts/registry_root.py`` to refresh the Merkle root.
"""

from __future__ import annotations

import argparse
import sys
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

ensure_src_on_path(_REPO_ROOT)
from build_video_posters import scrape_dod_filename  # noqa: E402
from pursue_index.scrape.manifest import load_manifest  # noqa: E402

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_DESKTOP = Path.home() / "Desktop" / "uap052226"
DEFAULT_NAS = Path("/mnt/nas/personal/pursue/r2-mirror/archive")
DEFAULT_BUCKET = "pursue-pdfs"
SOURCE_LABEL = "war.gov/release_02 (cloudfront videos bundle)"


def resolve_card_to_dod(card_id: str, dvids_id: str) -> str | None:
    """Wrap the public DVIDS scrape so we can log every miss."""
    fn = scrape_dod_filename(dvids_id)
    if not fn:
        print(f"[ingest] {card_id}: DVIDS {dvids_id} returned no DOD filename")
        return None
    return fn


def build_card_to_file_map(
    cards: list[Any], desktop_dir: Path
) -> tuple[dict[str, tuple[Any, Path]], list[str], list[Path]]:
    """Return (matched, unmatched_cards, unmatched_files).

    ``matched`` maps card_id -> (card, local_mp4_path).
    """
    available_files = {p.name: p for p in desktop_dir.glob("*.mp4")}
    matched: dict[str, tuple[Any, Path]] = {}
    unmatched_cards: list[str] = []
    matched_filenames: set[str] = set()

    for card in cards:
        if not card.dvids_video_id:
            unmatched_cards.append(card.card_id)
            continue
        dod_fn = resolve_card_to_dod(card.card_id, card.dvids_video_id)
        if not dod_fn:
            unmatched_cards.append(card.card_id)
            continue
        # Operator desktop files include the `video_2605_` prefix; match
        # by the DOD_<id>.mp4 suffix.
        hit = next(
            (
                (fname, fpath)
                for fname, fpath in available_files.items()
                if fname.endswith(dod_fn)
            ),
            None,
        )
        if not hit:
            unmatched_cards.append(card.card_id)
            print(
                f"[ingest] {card.card_id}: DVIDS {card.dvids_video_id} "
                f"-> {dod_fn} not in desktop dir"
            )
            continue
        fname, fpath = hit
        matched[card.card_id] = (card, fpath)
        matched_filenames.add(fname)

    unmatched_files = [
        p for fname, p in available_files.items() if fname not in matched_filenames
    ]
    return matched, unmatched_cards, unmatched_files


def ingest_one(
    card: Any,
    local_path: Path,
    *,
    client: Any,
    bucket: str,
    nas_dir: Path,
    registry_path: Path,
    skip_card_ids: set[str],
) -> str:
    """Return one of: 'skipped', 'uploaded', 'failed'."""
    card_id = card.card_id
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
        card, local_path, sha, size, archive_key, current_key, SOURCE_LABEL
    )
    append_registry(registry_path, entry)
    print(
        f"[ingest] {card_id}: archived sha={sha[:12]} size={size} "
        f"current={current_key}"
    )
    return "uploaded"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--desktop", type=Path, default=DEFAULT_DESKTOP)
    parser.add_argument("--nas", type=Path, default=DEFAULT_NAS)
    parser.add_argument("--bucket", type=str, default=DEFAULT_BUCKET)
    parser.add_argument(
        "--release-date",
        default="5/22/26",
        help="Manifest release_date to filter tranche-2 cards.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute mapping; do not upload."
    )
    return parser.parse_args(argv)


def _select_cards(manifest_path: Path, release_date: str) -> list[Any]:
    manifest = load_manifest(manifest_path)
    return [
        c
        for c in manifest.cards
        if c.asset_type == "VID" and c.release_date == release_date
    ]


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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env = read_env_file(_REPO_ROOT / ".env")
    vid_cards = _select_cards(args.manifest, args.release_date)
    print(f"[ingest] tranche-2 VID cards in manifest: {len(vid_cards)}")
    desktop_mp4s = sorted(args.desktop.glob("*.mp4"))
    print(f"[ingest] desktop MP4s: {len(desktop_mp4s)}")

    matched, unmatched_cards, unmatched_files = build_card_to_file_map(
        vid_cards, args.desktop
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
