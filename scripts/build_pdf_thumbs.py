"""Render page 1 of each PDF in the manifest to a WebP thumbnail.

Pipeline for the Gallery Phase 2 unlock. Each PDF card gets a tile in the gallery
DOCUMENTS tab; the tile shows the first page of the document.

Strategy:

  pdftocairo -jpeg -singlefile -r 100 <input.pdf> <tmp_prefix>
    → produces tmp_prefix.jpg (page 1 only, 100 DPI)

  convert <tmp.jpg> -resize 480x -quality 80 <out.webp>
    → 480px wide WebP, ~30-60 KB per file at q80

Idempotency: a sidecar ``.sha256`` records the bytes-hash of the
source PDF. On re-run, if the existing sidecar matches the current
PDF bytes, the thumbnail is up-to-date and we skip. If the PDF
changes (e.g., upstream replace), the sha mismatches and we
regenerate.

Output structure:
  web/public/data/thumbs/<card_id>.webp
  web/public/data/thumbs/<card_id>.sha256
  web/public/data/thumbs/index.json   {thumbs: {card_id: filename}, count: N}

Manifest source: data/manifests/latest.json (PDF cards only).
PDF location: <PURSUE_DATA_ROOT>/pdfs/<card_id>/<asset_filename>.
Falls back to skipping with a warning when the local PDF is absent
(operator hasn't downloaded that card yet).

Failure modes (all soft):
  * pdftocairo error (corrupt PDF, weird encryption) → log + skip
  * convert error → log + skip
  * Local PDF missing → log + skip
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile

from pursue_index.paths import repo_root

_REPO_ROOT = repo_root()

from pursue_index.config import settings
from pursue_index.scrape.manifest import load_manifest

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
# Tracks PURSUE_DATA_ROOT rather than baking in one operator's mount point.
DEFAULT_PDF_ROOT = settings.pdf_dir
DEFAULT_THUMBS_DIR = _REPO_ROOT / "web" / "public" / "data" / "thumbs"
DEFAULT_THUMB_WIDTH = 480
DEFAULT_QUALITY = 80


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def find_local_pdf(card_id: str, asset_filename: str | None, pdf_root: Path) -> Path | None:
    """Locate the local PDF for a card. Returns None when absent."""
    card_dir = pdf_root / card_id
    if not card_dir.is_dir():
        return None
    if asset_filename:
        # Most common — single file named after the upstream URL.
        candidate = card_dir / asset_filename
        if candidate.exists():
            return candidate
    # Fallback: first PDF in the dir.
    for p in card_dir.iterdir():
        if p.suffix.lower() == ".pdf":
            return p
    return None


def _run_tool(cmd: list[str], timeout: int, label: str, pdf: Path) -> bool:
    """Run one rendering tool; log and return False on any failure."""
    try:
        subprocess.check_call(cmd, timeout=timeout, stderr=subprocess.DEVNULL)
    except Exception as exc:
        print(f"[thumbs] {label} fail {pdf.name}: {exc}", flush=True)
        return False
    return True


def render_thumbnail(
    pdf: Path,
    out_webp: Path,
    *,
    width: int = DEFAULT_THUMB_WIDTH,
    quality: int = DEFAULT_QUALITY,
) -> bool:
    """pdftocairo → convert → WebP. Returns True on success."""
    out_webp.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pursue-thumb-") as tmpdir:
        prefix = Path(tmpdir) / "page1"
        # -singlefile drops the page suffix so output is exactly
        # <prefix>.jpg (no "-1" suffix to handle).
        render = ["pdftocairo", "-jpeg", "-singlefile", "-r", "100"]
        render += ["-f", "1", "-l", "1", str(pdf), str(prefix)]
        if not _run_tool(render, 60, "pdftocairo", pdf):
            return False
        jpg = prefix.with_suffix(".jpg")
        if not jpg.exists():
            print(f"[thumbs] pdftocairo produced no output for {pdf.name}", flush=True)
            return False
        resize = ["convert", str(jpg), "-resize", f"{width}x"]
        resize += ["-quality", str(quality), str(out_webp)]
        if not _run_tool(resize, 30, "convert", pdf):
            return False
        return out_webp.exists() and out_webp.stat().st_size > 0


def load_index(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return dict(data.get("thumbs", {}))


def save_index(path: Path, mapping: dict[str, str]) -> None:
    payload = {"thumbs": mapping, "count": len(mapping)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _prune_orphans(
    thumbs_dir: Path, valid_ids: set[str], mapping: dict[str, str]
) -> list[str]:
    """Drop index entries + files keyed to card_ids no longer in the manifest.

    A card that was superseded (new id for the same upstream asset) or
    dropped from the manifest otherwise keeps its stale thumbnail and
    sidecar on disk, and the dangling id in the index, forever.
    """
    removed: list[str] = []
    for cid in list(mapping):
        if cid not in valid_ids:
            mapping.pop(cid, None)
            removed.append(cid)
            (thumbs_dir / f"{cid}.webp").unlink(missing_ok=True)
            (thumbs_dir / f"{cid}.sha256").unlink(missing_ok=True)
    return removed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--pdf-root", type=Path, default=DEFAULT_PDF_ROOT)
    parser.add_argument("--thumbs-dir", type=Path, default=DEFAULT_THUMBS_DIR)
    parser.add_argument("--width", type=int, default=DEFAULT_THUMB_WIDTH)
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N cards (testing).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when the sidecar sha matches.",
    )
    return parser.parse_args(argv)


def _preflight(args: argparse.Namespace) -> bool:
    """Check required tools and the PDF root; print the reason on failure."""
    if shutil.which("pdftocairo") is None:
        print("[thumbs] pdftocairo not on PATH (apt install poppler-utils)")
        return False
    if shutil.which("convert") is None:
        print("[thumbs] convert not on PATH (apt install imagemagick)")
        return False
    if not args.pdf_root.exists():
        print(f"[thumbs] pdf root not found: {args.pdf_root}")
        return False
    return True


def _process_card(card, args: argparse.Namespace, mapping: dict[str, str]) -> str:
    """Handle one card; return the counts key for its outcome."""
    pdf = find_local_pdf(card.card_id, card.asset_filename, args.pdf_root)
    if pdf is None:
        return "no_local_pdf"

    webp = args.thumbs_dir / f"{card.card_id}.webp"
    sidecar = args.thumbs_dir / f"{card.card_id}.sha256"
    pdf_sha = sha256_file(pdf)

    had_prior = sidecar.exists() and webp.exists()
    if not args.force and had_prior and sidecar.read_text().strip() == pdf_sha:
        mapping[card.card_id] = webp.name
        return "fresh"

    if not render_thumbnail(pdf, webp, width=args.width, quality=args.quality):
        return "render_fail"

    sidecar.write_text(pdf_sha)
    mapping[card.card_id] = webp.name
    label = "regenerated" if had_prior else "new"
    size = webp.stat().st_size
    print(f"[thumbs] {label}: {card.card_id} -> {webp.name} ({size:,} B)", flush=True)
    return label


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _preflight(args):
        return 1

    manifest = load_manifest(args.manifest)
    pdf_cards = [c for c in manifest.cards if c.asset_type == "PDF"]
    if args.limit:
        pdf_cards = pdf_cards[: args.limit]
    print(f"[thumbs] processing {len(pdf_cards)} PDF cards")

    index_path = args.thumbs_dir / "index.json"
    mapping = load_index(index_path)

    counts = {
        "new": 0,
        "fresh": 0,
        "regenerated": 0,
        "no_local_pdf": 0,
        "render_fail": 0,
    }
    for card in pdf_cards:
        counts[_process_card(card, args, mapping)] += 1

    valid_ids = {c.card_id for c in pdf_cards}
    pruned = _prune_orphans(args.thumbs_dir, valid_ids, mapping)

    save_index(index_path, mapping)
    print(
        f"[thumbs] done: new={counts['new']} "
        f"regenerated={counts['regenerated']} "
        f"fresh={counts['fresh']} "
        f"render_fail={counts['render_fail']} "
        f"no_local_pdf={counts['no_local_pdf']} "
        f"pruned={len(pruned)}"
    )
    print(f"[thumbs] index.json: {len(mapping)} card→thumb mappings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
