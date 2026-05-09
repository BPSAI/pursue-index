#!/usr/bin/env python3
"""Build the static search payload for the web UI.

Walks ``settings.ocr_dir`` for ``pages.jsonl`` files, joins each page with
its card metadata from ``data/manifests/latest.json``, and writes a single
``web/public/data/pages.json`` array consumable by the MiniSearch island.

Run after ``pursue ocr run`` completes::

    python scripts/build_search_data.py

The output file is intentionally not committed (data/ derivatives belong
on the NAS); CI rebuilds it on each deploy from the OCR output that
gets synced into the runner. For now this is a manual local build that
you commit alongside the manifest, since OCR runs on the workstation.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "latest.json"
OUT_PATH = REPO_ROOT / "web" / "public" / "data" / "pages.json"

# Surya emits <b>...</b> and <u>...</u> markup even with math_mode=False; the
# corpus has no markup semantics, so strip these tags from the search payload
# (text between the tags is preserved). Tracked as ocr-gpu-surya follow-up #2.
_SURYA_TAG_RE = re.compile(r"</?(?:b|u|i)>")


def _clean_text(text: str) -> str:
    return _SURYA_TAG_RE.sub("", text)


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text())
    titles_by_id = {c["card_id"]: c["title"] for c in manifest["cards"]}

    docs: list[dict[str, object]] = []
    cards_seen = 0
    pages_seen = 0
    for card_dir in sorted(settings.ocr_dir.iterdir()) if settings.ocr_dir.exists() else []:
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
        title = titles_by_id.get(card_id, "(unknown)")
        cards_seen += 1
        with pages_path.open() as fh:
            for line in fh:
                row = json.loads(line)
                docs.append(
                    {
                        "id": f"{card_id}-p{row['page']}",
                        "card_id": card_id,
                        "page": row["page"],
                        "title": title,
                        "text": _clean_text(row["text"]),
                    }
                )
                pages_seen += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(docs, ensure_ascii=False))
    size_mb = OUT_PATH.stat().st_size / (1024 * 1024)
    print(
        f"wrote {OUT_PATH} ({size_mb:.1f} MB): {cards_seen} cards, {pages_seen} pages"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
