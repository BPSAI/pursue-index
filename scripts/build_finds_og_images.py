#!/usr/bin/env python3
"""Build per-entry OG images for ``/finds/<slug>`` pages.

Reads every ``web/src/content/finds/**/*.{md,mdx}`` entry, parses
the YAML frontmatter, and renders one PNG per non-draft entry to
``web/public/og/finds/<entry.id>.png``. Astro parity is the
load-bearing contract: recursive ``**/*.{md,mdx}`` glob, drop
``draft: true`` entries (matches Astro's ``getCollection`` filter),
and use the same ``c.id.slice(0, 8)`` prefix the source rail shows.

Idempotent: byte-stable for unchanged inputs. Safe to re-run on
every deploy.

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

# Astro source rail at [slug].astro:90 uses ``c.id.slice(0, 8)``.
_CARD_PREFIX_LEN = 8


def _build_card_index(manifest_path: Path) -> tuple[dict[str, dict], str]:
    """Return ``(card_id -> card, csv_sha256)`` for source-label lookups."""
    data = json.loads(manifest_path.read_text())
    return {c["card_id"]: c for c in data["cards"]}, data["csv_sha256"]


def _format_source_label(
    card_ids: tuple[str, ...], card_index: dict[str, dict]
) -> str:
    """Build a source label from the entry's first card.

    Format: ``AGENCY · prefix`` for single-card entries,
    ``AGENCY · prefix · 1 of N`` for multi-card entries so the picker
    is visible (entries like ``fbi-62-hq-83894-readers-guide.mdx``
    have 10 cards; the count makes the disambiguation explicit
    instead of silent).

    Falls back to ``ARCHIVE · prefix`` when the card_id isn't in the
    manifest, and to ``PURSUE://INDEX`` when the entry has no cards
    (shouldn't happen with current schema, kept defensive).
    """
    if not card_ids:
        return "PURSUE://INDEX"
    first = card_ids[0]
    card = card_index.get(first)
    agency = (card.get("agency") if card else None) or "ARCHIVE"
    base = f"{agency} · {first[:_CARD_PREFIX_LEN]}"
    if len(card_ids) > 1:
        return f"{base} · 1 of {len(card_ids)}"
    return base


def _enumerate_entries(finds_dir: Path) -> list[Path]:
    """Return sorted ``.md`` and ``.mdx`` entries under ``finds_dir``.

    Recursive — mirrors the Astro loader's ``**/*.{md,mdx}`` pattern
    so the script enumerates exactly the set of files Astro routes.
    """
    return sorted(
        list(finds_dir.rglob("*.md")) + list(finds_dir.rglob("*.mdx"))
    )


def _entry_id_for_path(mdx_path: Path, finds_dir: Path) -> str:
    """Compute Astro's ``entry.id`` for ``mdx_path``.

    Astro derives ``entry.id`` from the filesystem path relative to
    the content base, without extension — so ``foo/bar.mdx`` has
    ``entry.id == "foo/bar"`` and the URL is ``/finds/foo/bar``. We
    use the same value as the output PNG basename so
    ``/og/finds/<entry.id>.png`` resolves.
    """
    rel = mdx_path.relative_to(finds_dir)
    # Path.with_suffix("") drops only the final extension, which
    # matches Astro's behavior for `.md` / `.mdx`.
    return str(rel.with_suffix("")).replace("\\", "/")


def _assert_safe_slug(entry_id: str) -> None:
    """Refuse entry ids that would escape the out_dir.

    Defense-in-depth before writing the PNG. ``..`` segments,
    backslashes, and absolute-path-shaped strings are all rejected;
    nested forward-slash paths (``sub/nested``) remain accepted
    because Astro routes them and the script must mirror that.
    """
    if "\\" in entry_id:
        raise ValueError(f"unsafe slug (backslash): {entry_id!r}")
    parts = entry_id.split("/")
    if any(p in ("..", "") for p in parts):
        raise ValueError(f"unsafe slug (traversal/empty segment): {entry_id!r}")
    if Path(entry_id).is_absolute():
        raise ValueError(f"unsafe slug (absolute path): {entry_id!r}")


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


def _build_one(
    mdx: Path, finds_dir: Path, out_dir: Path, ctx_kwargs: dict
) -> tuple[str, int] | None:
    """Render one entry; return ``(entry_id, bytes)`` or None if skipped."""
    fm = parse_finds_frontmatter(mdx)
    if fm.draft:
        return None
    entry_id = _entry_id_for_path(mdx, finds_dir)
    _assert_safe_slug(entry_id)
    ctx = FindsOgContext(
        slug=entry_id,
        title=fm.title,
        subtitle=fm.subtitle,
        source_label=ctx_kwargs["source_label_fn"](fm.cards),
        csv_sha256=ctx_kwargs["csv_sha"],
        status_label=ctx_kwargs["status_label"],
    )
    out = out_dir / f"{entry_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_finds_og_image(ctx, out)
    return entry_id, out.stat().st_size


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    card_index, csv_sha = _build_card_index(args.manifest)
    entries = _enumerate_entries(args.finds_dir)
    if not entries:
        print(f"no entries found in {args.finds_dir}", file=sys.stderr)
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    ctx_kwargs = {
        "source_label_fn": lambda cards: _format_source_label(cards, card_index),
        "csv_sha": csv_sha,
        "status_label": args.status_label,
    }
    rendered: list[tuple[str, int]] = []
    skipped = 0
    for mdx in entries:
        result = _build_one(mdx, args.finds_dir, args.out_dir, ctx_kwargs)
        if result is None:
            skipped += 1
            continue
        rendered.append(result)
        entry_id, size = result
        print(f"  {entry_id:<48s} {size / 1024:6.1f} KB")
    total_bytes = sum(b for _, b in rendered)
    print(
        f"wrote {len(rendered)} images "
        f"(skipped {skipped} draft) "
        f"to {_format_out_path(args.out_dir)} "
        f"(total {total_bytes / 1024:.1f} KB, sha={csv_sha[:12]}…)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
