#!/usr/bin/env python3
"""Build per-entry OG images for ``/finds/<slug>`` pages.

Reads every ``web/src/content/finds/*.mdx`` entry, parses the YAML
frontmatter, looks up the first card_id in the manifest for an
``AGENCY · prefix`` source label, and renders one PNG per entry to
``web/public/og/finds/<slug>.png``.

Idempotent: re-running with unchanged inputs produces byte-stable
output, so this is safe to wire into a pre-build / pre-deploy step.

Usage::

    python scripts/build_finds_og_images.py
    python scripts/build_finds_og_images.py --finds-dir web/src/content/finds
    python scripts/build_finds_og_images.py --out-dir web/public/og/finds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.web.finds_og import (  # noqa: E402
    FindsOgContext,
    parse_finds_frontmatter,
    render_finds_og_image,
)

DEFAULT_FINDS_DIR = REPO_ROOT / "web" / "src" / "content" / "finds"
DEFAULT_OUT_DIR = REPO_ROOT / "web" / "public" / "og" / "finds"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"


def _build_card_index(manifest_path: Path) -> tuple[dict[str, dict], str]:
    """Return ``(card_id -> card, csv_sha256)`` for source-label lookups."""
    data = json.loads(manifest_path.read_text())
    return {c["card_id"]: c for c in data["cards"]}, data["csv_sha256"]


def _format_source_label(
    card_ids: tuple[str, ...], card_index: dict[str, dict]
) -> str:
    """Build a short ``AGENCY · prefix`` label from the entry's first card.

    Falls back to ``ARCHIVE · <prefix>`` if the card_id isn't in the
    manifest, and to ``PURSUE://INDEX`` if the entry has no cards at
    all (shouldn't happen with current schema but kept defensive).
    """
    if not card_ids:
        return "PURSUE://INDEX"
    first = card_ids[0]
    card = card_index.get(first)
    agency = (card.get("agency") if card else None) or "ARCHIVE"
    return f"{agency} · {first[:10]}"


def _format_out_path(out: Path) -> str:
    try:
        return str(out.relative_to(REPO_ROOT))
    except ValueError:
        return str(out)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--finds-dir", type=Path, default=DEFAULT_FINDS_DIR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--status-label", default="RESEARCH PREVIEW")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    card_index, csv_sha = _build_card_index(args.manifest)
    entries = sorted(args.finds_dir.glob("*.mdx"))
    if not entries:
        print(f"no .mdx entries found in {args.finds_dir}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    for mdx in entries:
        fm = parse_finds_frontmatter(mdx)
        ctx = FindsOgContext(
            slug=fm.slug,
            title=fm.title,
            subtitle=fm.subtitle,
            source_label=_format_source_label(fm.cards, card_index),
            csv_sha256=csv_sha,
            status_label=args.status_label,
        )
        out = args.out_dir / f"{fm.slug}.png"
        render_finds_og_image(ctx, out)
        size = out.stat().st_size
        total_bytes += size
        print(f"  {fm.slug:<48s} {size / 1024:6.1f} KB")
    print(
        f"wrote {len(entries)} images to {_format_out_path(args.out_dir)} "
        f"(total {total_bytes / 1024:.1f} KB, sha={csv_sha[:12]}…)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
