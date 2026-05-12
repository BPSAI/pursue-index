"""Extract poster frames from operator-downloaded DVIDS .mp4 files.

The PURSUE upstream listing carries `dvids_video_id` (a 7-digit DVIDS
asset identifier like 1006119) for video cards but does NOT carry a
direct download URL or thumbnail. The operator downloaded the 28
videos to ``~/Desktop/PERSUE/uapvideos/DOD_<dod_media_id>.mp4`` where
``dod_media_id`` is an 8-9 digit identifier that does NOT match the
DVIDS video id.

This script bridges the two:

  1. For each VID card in the manifest, scrape the public DVIDS web
     page (``https://www.dvidshub.net/video/<dvids_video_id>``) for
     the ``DOD_<id>.mp4`` filename.
  2. Match that filename against the operator's local video directory.
  3. Use ffmpeg to extract a poster frame at ~10% of duration (skips
     leader frames, captures actual content).
  4. Write the JPG to ``web/public/data/video-posters/<card_id>.jpg``.
  5. Maintain ``web/public/data/video-posters/index.json`` mapping
     card_id → poster filename so the GalleryIsland can render
     real posters in place of the placeholder.

Idempotency: skips cards whose poster already exists and is non-zero.
Re-runs are safe.

Failure modes (all soft):
  * DVIDS page returns no DOD_<id>.mp4 match → log + skip card
  * Local file missing → log + skip
  * ffmpeg failure → log + skip

The script does NOT mutate the manifest; the gallery reads the
sidecar JSON. Keeps the canonical manifest aligned with upstream.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import urllib.request

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape.manifest import load_manifest  # noqa: E402

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_VIDEO_DIR = Path.home() / "Desktop" / "PERSUE" / "uapvideos"
DEFAULT_POSTERS_DIR = _REPO_ROOT / "web" / "public" / "data" / "video-posters"

DOD_FILENAME_RE = re.compile(r"DOD_(\d{8,12})\.mp4")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


def scrape_dod_filename(dvids_video_id: str, timeout: float = 20.0) -> str | None:
    """Return ``DOD_<id>.mp4`` referenced on the DVIDS video page, or None.

    Public web scrape (no API key) — the asset filename appears in
    multiple places on the page (download links, embed metadata).
    First match wins; we don't care which surface yielded it.
    """
    url = f"https://www.dvidshub.net/video/{dvids_video_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[posters] dvids fetch fail {dvids_video_id}: {exc}")
        return None
    m = DOD_FILENAME_RE.search(body)
    return m.group(0) if m else None


def video_duration_seconds(path: Path) -> float | None:
    """Best-effort ffprobe duration. Returns None on failure."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            timeout=30,
        )
        return float(out.strip())
    except Exception:
        return None


def extract_poster(video: Path, out_jpg: Path, at_fraction: float = 0.1) -> bool:
    """Extract a single JPG poster at ``at_fraction * duration``.

    Returns True on success. The fraction skips the very first frame
    (often a fade-in or color bar) without committing to a fixed
    timestamp that would land outside short clips.
    """
    duration = video_duration_seconds(video)
    if duration is None or duration <= 0:
        return False
    seek = max(0.5, duration * at_fraction)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    try:
        # -ss before -i = fast seek (keyframe). -vframes 1 captures
        # one frame. -q:v 4 = decent quality JPG (~50-150 KB at 1080p).
        subprocess.check_call(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{seek:.3f}",
                "-i",
                str(video),
                "-vframes",
                "1",
                "-q:v",
                "4",
                "-vf",
                "scale=640:-1",
                str(out_jpg),
            ],
            timeout=60,
        )
        return out_jpg.exists() and out_jpg.stat().st_size > 0
    except Exception as exc:
        print(f"[posters] ffmpeg fail {video.name}: {exc}")
        return False


def load_index(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return dict(data.get("posters", {}))


def save_index(path: Path, mapping: dict[str, str]) -> None:
    payload = {
        "posters": mapping,
        "count": len(mapping),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument("--posters-dir", type=Path, default=DEFAULT_POSTERS_DIR)
    args = parser.parse_args(argv)

    if not args.video_dir.exists():
        print(f"[posters] video dir not found: {args.video_dir}")
        return 1

    manifest = load_manifest(args.manifest)
    vid_cards = [c for c in manifest.cards if c.asset_type == "VID"]
    print(f"[posters] {len(vid_cards)} VID cards in manifest")

    index_path = args.posters_dir / "index.json"
    mapping = load_index(index_path)

    counts = {"posters_kept": 0, "posters_new": 0, "skip_no_dod": 0, "skip_no_file": 0, "skip_ffmpeg": 0}

    for card in vid_cards:
        if not card.dvids_video_id:
            print(f"[posters] {card.card_id}: no dvids_video_id; skipping")
            counts["skip_no_dod"] += 1
            continue

        poster_path = args.posters_dir / f"{card.card_id}.jpg"
        if poster_path.exists() and poster_path.stat().st_size > 0:
            mapping[card.card_id] = poster_path.name
            counts["posters_kept"] += 1
            continue

        dod_filename = scrape_dod_filename(card.dvids_video_id)
        if not dod_filename:
            counts["skip_no_dod"] += 1
            continue

        video_file = args.video_dir / dod_filename
        if not video_file.exists():
            print(
                f"[posters] {card.card_id}: dvids={card.dvids_video_id} "
                f"→ {dod_filename} NOT in local dir"
            )
            counts["skip_no_file"] += 1
            continue

        ok = extract_poster(video_file, poster_path)
        if not ok:
            counts["skip_ffmpeg"] += 1
            continue
        mapping[card.card_id] = poster_path.name
        size = poster_path.stat().st_size
        print(
            f"[posters] new: {card.card_id} ← {dod_filename} "
            f"({size:,} B)"
        )
        counts["posters_new"] += 1

    save_index(index_path, mapping)
    print(
        f"[posters] done: new={counts['posters_new']} "
        f"kept={counts['posters_kept']} "
        f"skip_no_dod={counts['skip_no_dod']} "
        f"skip_no_file={counts['skip_no_file']} "
        f"skip_ffmpeg={counts['skip_ffmpeg']}"
    )
    print(f"[posters] index.json: {len(mapping)} card→poster mappings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
