#!/usr/bin/env python3
"""Build the social-share OG image at ``web/public/og.png``.

Reads ``data/manifests/latest.json`` for the live corpus stats so the
rendered card is always in sync with what the site actually serves.
Idempotent: re-running with the same manifest produces byte-stable
output, so this is safe to wire into a pre-build step.

Usage::

    python scripts/build_og_image.py
    python scripts/build_og_image.py --out web/public/og.png
    python scripts/build_og_image.py --pages 4153  # override page count

The page total isn't stored in the manifest (the manifest is per-card,
not per-page), so we accept it as a flag and fall back to a sensible
default. Once ``data/ocr/page_count.json`` (or similar) lands, swap the
default for a derived value.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.web.og_image import OgImageContext, render_og_image  # noqa: E402

DEFAULT_MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_OUT = REPO_ROOT / "web" / "public" / "og.png"
# Fallback when no page-count source is wired up yet. Update via --pages.
DEFAULT_PAGES = 4153


def _load_manifest_stats(path: Path) -> tuple[int, str]:
    data = json.loads(path.read_text())
    return len(data["cards"]), data["csv_sha256"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    p.add_argument("--source-host", default="war.gov")
    p.add_argument("--status-label", default="RESEARCH PREVIEW")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cards, sha = _load_manifest_stats(args.manifest)
    ctx = OgImageContext(
        cards=cards,
        pages=args.pages,
        csv_sha256=sha,
        source_host=args.source_host,
        status_label=args.status_label,
    )
    render_og_image(ctx, args.out)
    size_kb = args.out.stat().st_size / 1024
    print(
        f"wrote {args.out.relative_to(REPO_ROOT)} "
        f"({size_kb:.1f} KB, cards={cards}, pages={args.pages}, sha={sha[:12]}…)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
