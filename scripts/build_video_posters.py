"""Extract poster frames from our archived R2 A/V bytes.

Every VID/AUD card the site serves already has its canonical .mp4 bytes
in the three-tier archive: content-addressed in R2 as
``archive/<byte_sha256>.mp4`` (plus a ``<card_id>.mp4`` current-pointer)
and staged to the NAS-local mirror ``<PURSUE_DATA_ROOT>/r2-mirror/
archive/<byte_sha256>.mp4`` by the A/V ingest. This builder reads those
mirrored R2 bytes — NOT a DVIDS scrape and NOT the operator's Desktop —
so it covers ALL A/V cards (131 as of Release 5), on any machine with the
NAS mounted, credential-free (identical pattern to ``release/pdf_mirror``).

Flow, per VID/AUD card in ``data/manifests/latest.json``:

  1. Resolve ``card_id → byte_sha256`` from ``data/asset-bytes-registry.jsonl``
     (the row whose ``current_key`` is ``<card_id>.mp4``; last row wins).
  2. Locate ``<mirror_root>/archive/<byte_sha256>.mp4``.
  3. Use ffmpeg to extract a poster frame at ~10% of duration (skips
     leader frames, captures actual content).
  4. Write the JPG to ``web/public/data/video-posters/<card_id>.jpg`` and
     maintain the sibling ``index.json``: ``posters`` (card_id → poster
     filename) is what the GalleryIsland reads, and ``sources`` (card_id →
     the byte_sha256 the frame was extracted from) is what makes step 3
     skippable without going stale.
  5. Prune posters + index entries keyed to card_ids that are no longer
     A/V cards in the manifest (e.g. after a rename-heavy tranche).

Idempotent, but on the source bytes rather than on the filename: a card is
re-extracted when the registry's current sha differs from the one recorded
in ``sources``, so re-ingesting a card with new bytes refreshes its poster.
Checking only whether ``<card_id>.jpg`` exists would report such a card as
covered while it kept showing a frame of the superseded bytes.

Auto-invoked: ``make rebuild-derivatives`` runs this as one of the four
derived-payload builders, and ``ingest_run.promote_snapshot`` runs it on
every manifest promote. It is no longer an operator-only manual step.

Exit codes: returns 1 (loud failure) when the R2 mirror root is absent —
a misconfiguration the caller must fix, not silently tolerate. Per-card
gaps (no registry row, missing mirror byte, ffmpeg error) are counted and
logged but do not fail the run; the summary reports every skip.

The script does NOT mutate the manifest; the gallery reads the sidecar
JSON. The ``extract_dod_filename`` / ``scrape_dod_filename`` helpers below
are retained ONLY for ``scripts/ingest_release_videos.py`` (the A/V ingest
matcher that maps cards to operator-supplied files); poster generation no
longer touches DVIDS.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.scrape.manifest import load_manifest  # noqa: E402

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_POSTERS_DIR = _REPO_ROOT / "web" / "public" / "data" / "video-posters"

# Match the DOD asset id in ANY surface form the DVIDS page uses: a bare
# ``DOD_<id>.mp4`` download link (VID pages), a resolution-suffixed CDN URL
# ``DOD_<id>-1920x1080-9000k.mp4`` or a dotted ``DOD_<id>.0000001`` reference
# (AUD pages only carry these). Callers normalize the captured id back to the
# operator's canonical ``DOD_<id>.mp4`` filename via ``extract_dod_filename``.
DOD_FILENAME_RE = re.compile(r"DOD_(\d{8,12})")


def extract_dod_filename(body: str) -> str | None:
    """Return the canonical ``DOD_<id>.mp4`` for the first DOD id in ``body``.

    Normalizes every DVIDS surface form (bare, CDN resolution-suffixed, dotted
    sequence) to the clean filename the operator's downloaded files use, so the
    id matches whether it was scraped from a VID or an AUD page.
    """
    m = DOD_FILENAME_RE.search(body)
    return f"DOD_{m.group(1)}.mp4" if m else None
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"[posters] dvids fetch fail {dvids_video_id}: {exc}")
        return None
    return extract_dod_filename(body)


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


def _read_index(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_index(path: Path) -> dict[str, str]:
    """The ``card_id → poster filename`` map the gallery reads."""
    return dict(_read_index(path).get("posters", {}))


def load_source_shas(path: Path) -> dict[str, str]:
    """The ``card_id → byte_sha256`` the poster on disk was extracted from.

    Absent for an index written before posters recorded their source, in
    which case every card reads as stale and is regenerated once.
    """
    return dict(_read_index(path).get("sources", {}))


def save_index(path: Path, mapping: dict[str, str], sources: dict[str, str]) -> None:
    payload = {
        "posters": mapping,
        "sources": sources,
        "count": len(mapping),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def load_registry_sha_map(registry_path: Path) -> dict[str, str]:
    """Map ``card_id → byte_sha256`` for every ``<card_id>.mp4`` registry row.

    Only rows whose ``current_key`` is an ``.mp4`` current-pointer are the
    canonical A/V bytes we serve. A card re-ingested with new bytes has a
    later row, and last row wins, so this map always names the bytes the
    site currently serves — which is what makes the poster on disk
    checkable against them.
    """
    out: dict[str, str] = {}
    if not registry_path.exists():
        return out
    for raw in registry_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not (row.get("current_key") or "").endswith(".mp4"):
            continue
        cid, sha = row.get("card_id"), row.get("byte_sha256")
        if cid and sha:
            out[cid] = sha
    return out


def _resolve_mirror_mp4(mirror_root: Path, sha: str) -> Path | None:
    """The NAS-local mirror of the R2 ``archive/<sha>.mp4`` object, or None."""
    path = mirror_root / "archive" / f"{sha}.mp4"
    return path if path.is_file() else None


def _poster_is_current(poster_path: Path, recorded_sha: str | None, sha: str) -> bool:
    """Is the poster on disk the one extracted from the bytes we serve now?

    Presence alone is not the question. A card re-ingested with new bytes
    keeps its card_id and its poster filename, so an existence check reads
    a poster of the superseded bytes as current and the card reports
    covered forever. The recorded source sha is what distinguishes them.
    """
    if not (poster_path.exists() and poster_path.stat().st_size > 0):
        return False
    return recorded_sha == sha


def _generate_one_poster(
    card_id: str,
    sha_map: dict[str, str],
    mirror_root: Path,
    posters_dir: Path,
    state: tuple[dict[str, str], dict[str, str]],
    counts: dict[str, int],
) -> None:
    """Poster one A/V card from its mirrored R2 bytes; mutate state/counts.

    ``state`` is the ``(mapping, sources)`` pair persisted to index.json.
    """
    mapping, sources = state
    poster_path = posters_dir / f"{card_id}.jpg"
    existing = poster_path.exists() and poster_path.stat().st_size > 0
    sha = sha_map.get(card_id)
    if not sha:
        if existing:
            # No registry row to check against; the poster we already have
            # is the best available answer, so keep it rather than delete
            # coverage we cannot re-derive.
            mapping[card_id] = poster_path.name
            counts["kept"] += 1
            return
        print(f"[posters] {card_id}: no <card_id>.mp4 registry row; skipping")
        counts["skip_no_sha"] += 1
        return
    if _poster_is_current(poster_path, sources.get(card_id), sha):
        mapping[card_id] = poster_path.name
        counts["kept"] += 1
        return
    mp4 = _resolve_mirror_mp4(mirror_root, sha)
    if mp4 is None:
        print(f"[posters] {card_id}: r2 mirror byte archive/{sha[:12]}….mp4 absent")
        counts["skip_no_bytes"] += 1
        return
    if not extract_poster(mp4, poster_path):
        counts["skip_ffmpeg"] += 1
        return
    mapping[card_id] = poster_path.name
    sources[card_id] = sha
    counts["refreshed" if existing else "new"] += 1
    verb = "refreshed" if existing else "new"
    print(f"[posters] {verb}: {card_id} ← archive/{sha[:12]}….mp4 "
          f"({poster_path.stat().st_size:,} B)")


def _prune_orphans(
    posters_dir: Path,
    valid_ids: set[str],
    mapping: dict[str, str],
    sources: dict[str, str] | None = None,
) -> list[str]:
    """Drop index entries + JPGs keyed to card_ids that are no longer A/V cards.

    Covers the mapping, the recorded source shas, and any stray
    ``<card_id>.jpg`` on disk (a poster whose card was renamed/removed
    lingers otherwise), so coverage counts reflect only live cards.
    """
    sources = {} if sources is None else sources
    removed: list[str] = []
    for cid in list(mapping):
        if cid not in valid_ids:
            mapping.pop(cid, None)
            removed.append(cid)
    for cid in list(sources):
        if cid not in valid_ids:
            sources.pop(cid, None)
    for jpg in sorted(posters_dir.glob("*.jpg")):
        if jpg.stem not in valid_ids:
            jpg.unlink()
            if jpg.stem not in removed:
                removed.append(jpg.stem)
    return removed


def build(
    *,
    manifest_path: Path,
    registry_path: Path,
    mirror_root: Path,
    posters_dir: Path,
) -> int:
    """Rebuild every A/V card's poster from mirrored R2 bytes; prune orphans."""
    manifest = load_manifest(manifest_path)
    # AUD items are DVIDS audio wrapped in an mp4 that runs a static agency
    # logo card (e.g. the NASA logo on the Apollo debriefings), so a poster
    # frame is just as valid a thumbnail for them as for VID clips.
    valid_ids = {c.card_id for c in manifest.cards if c.asset_type in ("VID", "AUD")}
    print(f"[posters] {len(valid_ids)} VID/AUD cards in manifest")
    sha_map = load_registry_sha_map(registry_path)

    posters_dir.mkdir(parents=True, exist_ok=True)
    index_path = posters_dir / "index.json"
    mapping = load_index(index_path)
    sources = load_source_shas(index_path)
    counts = {
        "kept": 0,
        "new": 0,
        "refreshed": 0,
        "skip_no_sha": 0,
        "skip_no_bytes": 0,
        "skip_ffmpeg": 0,
    }

    for card_id in sorted(valid_ids):
        _generate_one_poster(
            card_id, sha_map, mirror_root, posters_dir, (mapping, sources), counts
        )
    removed = _prune_orphans(posters_dir, valid_ids, mapping, sources)

    save_index(index_path, mapping, sources)
    print(
        f"[posters] done: new={counts['new']} refreshed={counts['refreshed']} "
        f"kept={counts['kept']} "
        f"pruned={len(removed)} skip_no_sha={counts['skip_no_sha']} "
        f"skip_no_bytes={counts['skip_no_bytes']} skip_ffmpeg={counts['skip_ffmpeg']}"
    )
    print(
        f"[posters] index.json: {len(mapping)}/{len(valid_ids)} A/V cards covered"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--mirror-root",
        type=Path,
        default=None,
        help="R2 mirror root (default: <PURSUE_DATA_ROOT>/r2-mirror).",
    )
    parser.add_argument("--posters-dir", type=Path, default=DEFAULT_POSTERS_DIR)
    args = parser.parse_args(argv)

    mirror_root = args.mirror_root
    if mirror_root is None:
        from pursue_index.config import settings  # lazy: avoid .env at import

        mirror_root = settings.data_root / "r2-mirror"
    if not mirror_root.exists():
        print(f"[posters] r2 mirror root not found: {mirror_root}")
        return 1

    return build(
        manifest_path=args.manifest,
        registry_path=args.registry,
        mirror_root=mirror_root,
        posters_dir=args.posters_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
