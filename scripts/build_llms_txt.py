#!/usr/bin/env python3
"""Regenerate the manifest-derived sections of llms.txt / llms-full.txt.

These two discovery surfaces were hand-maintained, so a tranche that added cards
left them describing the previous release with nothing to catch it. This script
rewrites the `## Cards` section of each from the manifest and stamps a
provenance line the ship path can check.

Deliberately narrow: a tranche changes cards, counts and the manifest sha. The
hand-written prose sections and the editorial `/finds` articles inlined in
llms-full.txt are preserved byte-for-byte — this is not a whole-document
rewriter, and it must not become one.

Usage:
    python scripts/build_llms_txt.py            # regenerate in place
    python scripts/build_llms_txt.py --check    # exit 1 if stale (ship gate)
    python scripts/build_llms_txt.py --diff     # show what would change
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pursue_index.config import settings  # noqa: E402
from pursue_index.geo.llms import (  # noqa: E402
    EXCERPT_CHARS,
    build_cards_intro,
    build_provenance_line,
    card_index_line,
    check_geo_freshness,
    parse_existing_excerpts,
    parse_provenance,
    render_card_detail,
    render_freshness_report,
    replace_section,
    resolve_excerpt,
    should_include_excerpt,
)

DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
LLMS_TXT = _REPO_ROOT / "web" / "public" / "llms.txt"
LLMS_FULL_TXT = _REPO_ROOT / "web" / "public" / "llms-full.txt"

EXCERPT_PAGE = "1"


def first_page_excerpt(card_id: str, *, ocr_dir: Path) -> str | None:
    """Page-1 OCR text, whitespace-collapsed and truncated.

    Returns None when the OCR tier is not mounted or the card has no text
    layer (video/audio/image cards) — the excerpt block is then omitted rather
    than emitted empty.
    """
    path = ocr_dir / card_id / "pages.jsonl"
    if not path.exists():
        return None

    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if str(record.get("page")) != EXCERPT_PAGE:
                    continue
                text = re.sub(r"\s+", " ", record.get("text") or "").strip()
                return text[:EXCERPT_CHARS] or None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _stamp_provenance(document: str, line: str) -> str:
    """Insert or update the provenance line directly under the H1 blurb."""
    if parse_provenance(document) is not None:
        return re.sub(r"^>\s*Manifest:.*$", line, document, count=1, flags=re.MULTILINE)

    # Place it immediately before the first `## ` section heading.
    match = re.search(r"^##[ \t]+", document, re.MULTILINE)
    if match is None:
        return f"{document.rstrip()}\n\n{line}\n"
    return f"{document[: match.start()]}{line}\n\n{document[match.start() :]}"


def render_documents(manifest: dict, *, ocr_dir: Path) -> dict[Path, str]:
    cards = manifest["cards"]
    provenance = build_provenance_line(
        card_count=len(cards), csv_sha256=manifest["csv_sha256"]
    )

    index_doc = LLMS_TXT.read_text(encoding="utf-8")
    full_doc = LLMS_FULL_TXT.read_text(encoding="utf-8")

    # Already-published excerpts are the fallback when the OCR tier is thin, so
    # regenerating on a partially-mounted machine refreshes what it can instead
    # of deleting text it merely cannot see.
    published = parse_existing_excerpts(full_doc)

    index_body = "\n".join(card_index_line(card) for card in cards)
    detail_body = "\n\n".join(
        render_card_detail(
            card,
            excerpt=(
                resolve_excerpt(
                    (card["card_id"], card["title"]),
                    live=first_page_excerpt(card["card_id"], ocr_dir=ocr_dir),
                    published=published,
                )
                if should_include_excerpt(
                    card,
                    already_published=(card["card_id"], card["title"]) in published,
                )
                else None
            ),
        )
        for card in cards
    )
    full_body = f"{build_cards_intro(card_count=len(cards))}\n\n{detail_body}"

    out: dict[Path, str] = {}
    for path, document, body in (
        (LLMS_TXT, index_doc, index_body),
        (LLMS_FULL_TXT, full_doc, full_body),
    ):
        out[path] = _stamp_provenance(
            replace_section(document, "Cards", body), provenance
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--ocr-dir", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="exit 1 if stale")
    parser.add_argument("--diff", action="store_true", help="print a unified diff")
    args = parser.parse_args(argv)

    ocr_dir = args.ocr_dir or settings.ocr_dir
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    rendered = render_documents(manifest, ocr_dir=ocr_dir)

    if args.check:
        # Compare RENDERED CONTENT, not just the provenance line. Card metadata
        # can change without moving the count or the upstream csv_sha256 — a
        # curated display_date overlay does exactly that — and a hand-edit moves
        # neither. Rendering and diffing catches all three.
        #
        # Safe without the NAS mounted: with no live OCR every excerpt falls
        # back to the published text, so the render is deterministic in CI.
        stale = [
            path.name
            for path, new in rendered.items()
            if path.read_text(encoding="utf-8") != new
        ]
        result = check_geo_freshness(
            card_count=len(manifest["cards"]),
            csv_sha256=manifest["csv_sha256"],
            documents={
                p.name: p.read_text(encoding="utf-8") for p in (LLMS_TXT, LLMS_FULL_TXT)
            },
        )
        if stale:
            print(
                "GEO discovery metadata is STALE — regenerate with "
                "`python scripts/build_llms_txt.py`:"
            )
            for name in stale:
                print(f"  * {name}: rendered output differs from the committed file")
            for problem in result.problems:
                print(f"  * {problem}")
            return 1
        print(render_freshness_report(result))
        return 0 if result.ok else 1

    if args.diff:
        for path, new in rendered.items():
            old = path.read_text(encoding="utf-8")
            diff = difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
            sys.stdout.writelines(diff)
        return 0

    for path, new in rendered.items():
        path.write_text(new, encoding="utf-8")
        print(f"[geo] wrote {path.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
