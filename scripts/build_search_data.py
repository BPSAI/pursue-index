#!/usr/bin/env python3
"""Build the static search payload for the web UI.

Walks ``settings.ocr_dir`` for ``pages.jsonl`` files, joins each page with
its card metadata from ``data/manifests/latest.json``, and writes a single
``web/public/data/pages.json`` array consumable by the MiniSearch island.

Run after ``pursue ocr run`` completes::

    python scripts/build_search_data.py

When the embed pipeline ran with ``--augment-from`` (i.e. the deployed
``embeddings/{model}/index.json`` carries an ``augmented_by`` block),
this script must apply the same atlas-join lookup and append the
``[[IMAGE-DESCRIPTIONS via ...]]`` block to each matching page's
``text``. Otherwise the chat prompt + citation snippets read straight
from un-augmented OCR while the vectors retrieve against augmented text
(vaivora cross-cutting blocker #1)::

    python scripts/build_search_data.py \
        --augment-from data/external/alex-zhang42-corpus.jsonl

The output file is intentionally not committed (data/ derivatives belong
on the NAS); CI rebuilds it on each deploy from the OCR output that
gets synced into the runner. For now this is a manual local build that
you commit alongside the manifest, since OCR runs on the workstation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages.json"
DEFAULT_AUGMENT_CORPUS = (
    REPO_ROOT / "data" / "external" / "alex-zhang42-corpus.jsonl"
)

# Surya emits <b>...</b> and <u>...</u> markup even with math_mode=False; the
# corpus has no markup semantics, so strip these tags from the search payload
# (text between the tags is preserved). Tracked as ocr-gpu-surya follow-up #2.
_SURYA_TAG_RE = re.compile(r"</?(?:b|u|i)>")


def _clean_text(text: str) -> str:
    return _SURYA_TAG_RE.sub("", text)


def _read_index_augmentation(
    embeddings_root: Path, embed_model: str
) -> dict | None:
    """Return the embed run's ``augmented_by`` block, or ``None``.

    Probes ``{embeddings_root}/{embed_model}/index.json``. The block's
    presence is the signal that the search payload must apply the
    image-tag lookup; its absence means the payload is plain OCR text.
    """
    idx_path = embeddings_root / embed_model / "index.json"
    if not idx_path.exists():
        return None
    payload = json.loads(idx_path.read_text())
    return payload.get("augmented_by")


def _build_augment_lookup(
    augment_corpus: Path,
    manifest_path: Path,
    miss_rate_threshold: float,
) -> dict[tuple[str, int], list[str]]:
    """Reuse the embed pipeline's atlas_join to mirror its lookup table.

    Critical: this must match what ``embed/store.py::_augment_text`` saw
    so the text in ``pages.json`` is byte-equivalent to the text the
    embed run hashed. Anything else and the chat prompt won't match
    its retrieval slots.
    """
    from pursue_index.embed.atlas_join import load_atlas_index
    from pursue_index.scrape import load_manifest

    manifest = load_manifest(manifest_path)
    return load_atlas_index(
        augment_corpus, manifest, miss_rate_threshold=miss_rate_threshold
    )


def _maybe_augment_text(
    card_id: str,
    page: int,
    text: str,
    augment_lookup: dict[tuple[str, int], list[str]] | None,
) -> str:
    """Apply the same IMAGE-DESCRIPTIONS block embed/store.py applies."""
    if augment_lookup is None:
        return text
    tags = augment_lookup.get((card_id, page))
    if not tags:
        return text
    from pursue_index.embed.store import _augment_text

    return _augment_text(text, tags)


def _load_titles(manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text())
    return {c["card_id"]: c["title"] for c in manifest["cards"]}


def _walk_card_pages(
    ocr_dir: Path,
    titles_by_id: dict[str, str],
    augment_lookup: dict[tuple[str, int], list[str]] | None,
) -> tuple[list[dict[str, object]], int]:
    """Walk OCR cards and emit per-page docs. Returns (docs, cards_seen)."""
    docs: list[dict[str, object]] = []
    cards_seen = 0
    if not ocr_dir.exists():
        return docs, cards_seen
    for card_dir in sorted(ocr_dir.iterdir()):
        if not card_dir.is_dir():
            continue
        meta_path = card_dir / "meta.json"
        pages_path = card_dir / "pages.jsonl"
        if not (meta_path.exists() and pages_path.exists()):
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("status") != "ok":
            continue
        card_id = card_dir.name
        title = titles_by_id.get(card_id)
        if title is None:
            # Card not in the current manifest (e.g. an upstream-removed
            # re-encode whose live successor card_id now carries the content):
            # its OCR dir lingers on NAS but it must not enter the public
            # search index — the site renders cards only from the manifest, so
            # an indexed-but-unlisted card is a search result with no page.
            print(f"  skip (not in manifest): {card_id}", file=sys.stderr)
            continue
        cards_seen += 1
        docs.extend(
            _emit_card_pages(card_id, title, pages_path, augment_lookup)
        )
    return docs, cards_seen


def _emit_card_pages(
    card_id: str,
    title: str,
    pages_path: Path,
    augment_lookup: dict[tuple[str, int], list[str]] | None,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    with pages_path.open() as fh:
        for line in fh:
            row = json.loads(line)
            page = int(row["page"])
            text = _maybe_augment_text(
                card_id, page, _clean_text(row["text"]), augment_lookup
            )
            out.append(
                {
                    "id": f"{card_id}-p{page}",
                    "card_id": card_id,
                    "page": page,
                    "title": title,
                    "text": text,
                    "engine": row.get("engine", "unknown"),
                    "confidence": row.get("confidence", 0),
                }
            )
    return out


def _resolve_augment_lookup(
    embeddings_root: Path,
    embed_model: str,
    augment_corpus: Path | None,
    manifest_path: Path,
    augment_miss_rate_threshold: float,
) -> dict[tuple[str, int], list[str]] | None:
    """Resolve the augment lookup OR raise on the bridge-script bug."""
    augmented_by = _read_index_augmentation(embeddings_root, embed_model)
    if augmented_by is None:
        return None
    if augment_corpus is None:
        raise RuntimeError(
            f"embeddings/{embed_model}/index.json declares augmentation "
            f"({augmented_by.get('dataset', '?')}) but no --augment-from "
            f"corpus was supplied. Refusing to write pages.json that's "
            f"out of sync with the deployed vectors. Pass the same "
            f"corpus path the embed run used."
        )
    return _build_augment_lookup(
        augment_corpus, manifest_path, augment_miss_rate_threshold
    )


def build(
    ocr_dir: Path,
    manifest_path: Path,
    out_path: Path,
    embeddings_root: Path,
    embed_model: str,
    augment_corpus: Path | None = None,
    augment_miss_rate_threshold: float = 0.01,
) -> int:
    """Materialize the search payload. Returns process exit code."""
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    augment_lookup = _resolve_augment_lookup(
        embeddings_root, embed_model, augment_corpus, manifest_path,
        augment_miss_rate_threshold,
    )
    titles_by_id = _load_titles(manifest_path)
    docs, cards_seen = _walk_card_pages(
        ocr_dir, titles_by_id, augment_lookup
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(docs, ensure_ascii=False))
    size_mb = out_path.stat().st_size / (1024 * 1024)
    augmented_pages = sum(
        1 for d in docs if "IMAGE-DESCRIPTIONS" in str(d["text"])
    )
    extra = (
        f"; {augmented_pages} pages augmented" if augment_lookup else ""
    )
    print(
        f"wrote {out_path} ({size_mb:.1f} MB): {cards_seen} cards, "
        f"{len(docs)} pages{extra}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ocr-dir", type=Path, default=settings.ocr_dir,
        help="Where OCR output cards live (defaults to settings.ocr_dir).",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST_PATH,
        help="Path to the canonical scrape manifest.",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_PATH,
        help="Where to write web/public/data/pages.json.",
    )
    parser.add_argument(
        "--embeddings-root", type=Path, default=settings.embeddings_dir,
        help="Per-model embed output root (used to detect augmentation).",
    )
    parser.add_argument(
        "--embed-model", default=settings.embed_model,
        help="Embed model id (matches the embed-stage directory).",
    )
    parser.add_argument(
        "--augment-from", type=Path, default=None,
        help=(
            "alex-zhang42 corpus.jsonl path. Required when "
            "embeddings/<model>/index.json carries augmented_by — "
            "otherwise pages.json would be out of sync with the vectors."
        ),
    )
    parser.add_argument(
        "--augment-miss-rate-threshold", type=float, default=0.01,
        help="Atlas join miss-rate ceiling (default 1%%).",
    )
    args = parser.parse_args()
    return build(
        ocr_dir=args.ocr_dir,
        manifest_path=args.manifest,
        out_path=args.out,
        embeddings_root=args.embeddings_root,
        embed_model=args.embed_model,
        augment_corpus=args.augment_from,
        augment_miss_rate_threshold=args.augment_miss_rate_threshold,
    )


if __name__ == "__main__":
    sys.exit(main())
