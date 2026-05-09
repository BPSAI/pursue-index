"""Test the per-entry OG image builder for /finds/<slug> entries.

The builder must:

1. Parse each ``web/src/content/finds/*.mdx`` frontmatter, picking up
   the entry slug (filename), title, subtitle, and first card_id.
2. Render a per-entry 1200x630 PNG that reuses the same site OG aesthetic
   (dark bg, scanlines, corner brackets, stamp, footer) but replaces the
   PURSUE://INDEX lockup with the entry title (wrapped/truncated as needed).
3. Stay byte-stable: same inputs => same PNG bytes (so re-runs in CI don't
   churn ``web/public/og/finds/<slug>.png``).
4. Render legibly at 600x315 thumbnail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pursue_index.web.finds_og import (
    FindsOgContext,
    parse_finds_frontmatter,
    render_finds_og_image,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FINDS_DIR = REPO_ROOT / "web" / "src" / "content" / "finds"
FINDS_OG_DIR = REPO_ROOT / "web" / "public" / "og" / "finds"


@pytest.fixture
def ctx() -> FindsOgContext:
    """Stable inputs so the test is deterministic across machines."""
    return FindsOgContext(
        slug="apollo-17",
        title="Apollo 17 Crew Debriefing — What's Actually There",
        subtitle="An exercise in expectation calibration",
        source_label="NASA · 0b298cfc",
        csv_sha256="596cc1881aa97d2fa49a45edab14d60802616e73ce125d286120e00d967cafa2",
        status_label="RESEARCH PREVIEW",
    )


# --- Frontmatter parser ---------------------------------------------------


def test_parse_frontmatter_extracts_required_fields(tmp_path: Path) -> None:
    mdx = tmp_path / "sample.mdx"
    mdx.write_text(
        '---\n'
        'title: "Sample Entry — A Test"\n'
        'subtitle: "A short subtitle"\n'
        'summary: "Long summary here, may wrap across lines."\n'
        'tags: [a, b]\n'
        'cards:\n'
        '  - 0b298cfc9c65a4d6\n'
        '  - aabbccddeeff0011\n'
        'published: 2026-05-09\n'
        '---\n'
        '\nbody content\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.slug == "sample"
    assert fm.title == "Sample Entry — A Test"
    assert fm.subtitle == "A short subtitle"
    assert fm.cards == ("0b298cfc9c65a4d6", "aabbccddeeff0011")


def test_parse_frontmatter_subtitle_is_optional(tmp_path: Path) -> None:
    mdx = tmp_path / "no-subtitle.mdx"
    mdx.write_text(
        '---\n'
        'title: "Only Title"\n'
        'cards:\n'
        '  - aabbccddeeff0011\n'
        '---\n'
    )
    fm = parse_finds_frontmatter(mdx)
    assert fm.title == "Only Title"
    assert fm.subtitle is None


# --- Render: shape + byte stability ---------------------------------------


def test_render_produces_correct_dimensions(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        assert im.size == (1200, 630)
        assert im.format == "PNG"


def test_render_under_200kb(tmp_path: Path, ctx: FindsOgContext) -> None:
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    assert out.stat().st_size < 200 * 1024


def test_render_is_byte_stable(tmp_path: Path, ctx: FindsOgContext) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    render_finds_og_image(ctx, a)
    render_finds_og_image(ctx, b)
    assert a.read_bytes() == b.read_bytes()


def test_render_differs_per_entry(tmp_path: Path, ctx: FindsOgContext) -> None:
    """Two different entries must produce different PNGs — otherwise the
    per-entry override is a no-op and Slack/Twitter scrapers will see the
    same image regardless of slug."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    render_finds_og_image(ctx, a)
    other = FindsOgContext(
        slug="muroc-1947",
        title="The Muroc AAF Sightings, July 8, 1947",
        subtitle="Five sworn statements from Edwards-AFB-before-it-was-Edwards-AFB",
        source_label="FBI · 99c12a9c",
        csv_sha256=ctx.csv_sha256,
        status_label=ctx.status_label,
    )
    render_finds_og_image(other, b)
    assert a.read_bytes() != b.read_bytes()


# --- Render: visual sanity (not blank, declassified stamp, footer) --------


def _count_pixels(band: Image.Image, *, predicate: object, step: int = 4) -> int:
    n = 0
    for y in range(0, band.height, step):
        for x in range(0, band.width, step):
            r, g, b = band.getpixel((x, y))[:3]
            if predicate(r, g, b):  # type: ignore[operator]
                n += 1
    return n


def test_title_band_has_bright_pixels(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    """The entry title sits in the upper-mid band; assert it's actually
    drawn there so a future refactor that drops the title layer fails."""
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((80, 180, 1120, 360))

        def is_bright(r: int, g: int, b: int) -> bool:
            return r + g + b > 300

        bright = _count_pixels(band, predicate=is_bright)
        assert bright > 200, f"title band too sparse: {bright}"


def test_declassified_stamp_renders_red(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    """Same DECLASSIFIED stamp as default OG (shared layer)."""
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((640, 60, 1200, 320))

        def is_red(r: int, g: int, b: int) -> bool:
            return r > 130 and g < 90 and b < 90

        red = _count_pixels(band, predicate=is_red)
        assert red > 50, f"DECLASSIFIED stamp absent: {red}"


def test_footer_status_pill_renders_amber(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((100, 530, 700, 580))

        def is_amber(r: int, g: int, b: int) -> bool:
            return r > 220 and g > 150 and b < 130

        amber = _count_pixels(band, predicate=is_amber, step=2)
        assert amber > 20, f"footer status pill absent: {amber}"


def test_sha256_line_renders_dim_text(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    out = tmp_path / "og.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((100, 440, 600, 470))

        def is_dim_text(r: int, g: int, b: int) -> bool:
            return 150 < r < 230 and 150 < g < 230 and 150 < b < 240 and abs(r - g) < 30

        dim = _count_pixels(band, predicate=is_dim_text, step=2)
        assert dim > 30, f"sha256 line absent: {dim}"


# --- Long title handling --------------------------------------------------


def test_long_title_does_not_crash_or_overflow(tmp_path: Path) -> None:
    """A very long title must be wrapped or truncated and still render
    a valid PNG. Composition cannot break on long input."""
    long_title = (
        "This Is An Unreasonably Long Entry Title That Certainly Will Not "
        "Fit On One Line Of The OG Image Because It Is Designed To Force "
        "Wrap Or Truncate Behavior In The Renderer"
    )
    ctx = FindsOgContext(
        slug="long-title-test",
        title=long_title,
        subtitle=None,
        source_label="TEST · 00000000",
        csv_sha256="0" * 64,
        status_label="RESEARCH PREVIEW",
    )
    out = tmp_path / "long.png"
    render_finds_og_image(ctx, out)
    with Image.open(out) as im:
        assert im.size == (1200, 630)


def test_long_unspaced_token_is_hard_broken(tmp_path: Path) -> None:
    """A 300-char run with no whitespace (e.g. a long URL or hash)
    cannot stay on one line — it would render past the right margin
    and through the corner brackets / DECLASSIFIED stamp area on the
    public OG card. The wrapper must break by character before the
    greedy word-wrap claims the token whole.

    Asserted via the public ``_wrap_title`` helper to keep the test
    fast and focused; the renderer-level smoke is covered by the
    generic ``test_long_title_does_not_crash_or_overflow`` above.
    """
    from PIL import ImageDraw

    from pursue_index.web import og_fonts as fonts
    from pursue_index.web.finds_og import _wrap_title

    im = Image.new("RGBA", (1200, 630), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    f = fonts.mono(44, bold=True)
    blob = "A" * 300
    lines = _wrap_title(blob, draw=draw, font=f, max_width=940, max_lines=3)
    assert len(lines) <= 3
    for line in lines:
        # Each line must measure within the title box. The previous
        # implementation returned one ~300-char line that overflowed.
        assert draw.textlength(line, font=f) <= 940, (
            f"line {line!r} overflows max_width=940"
        )


# --- Subtitle truncation ellipsis symmetry --------------------------------


def test_subtitle_fallback_ellipsizes_when_truncated(
    tmp_path: Path, ctx: FindsOgContext
) -> None:
    """When ``subtitle is None``, the slug-breadcrumb fallback
    ``/FINDS/<slug>`` must apply the same ellipsis logic as a real
    truncated subtitle. A long-slug fallback must end in ``…`` if it
    was shortened, not silently hide the truncation.
    """
    from PIL import ImageDraw

    from pursue_index.web import og_fonts as fonts
    from pursue_index.web.finds_og import _truncate_with_ellipsis

    im = Image.new("RGBA", (1200, 630), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    f = fonts.sans(24)
    super_long_slug = "x" * 400
    # Pretend it was a fallback (subtitle=None, original=fallback string).
    fallback = f"/FINDS/{super_long_slug}"
    out = _truncate_with_ellipsis(
        fallback, draw=draw, font=f, max_width=940, original=fallback
    )
    assert out.endswith("…"), (
        f"fallback truncation must end in ellipsis, got {out!r}"
    )


# --- Committed-PNG byte-equality regression catch -------------------------


def test_apollo_17_committed_png_matches_fresh_render(tmp_path: Path) -> None:
    """Re-render apollo-17 with the same context the build script
    produces and assert byte-equality with the on-disk PNG. If anyone
    tweaks the renderer without re-running the build script, the
    committed PNGs go stale and previously-passing tests would mask
    that drift; this test makes the byte-stability claim load-bearing
    in CI.
    """
    if not FINDS_DIR.exists():
        pytest.skip("finds content dir not present")
    committed = FINDS_OG_DIR / "apollo-17.png"
    if not committed.exists():
        pytest.skip("committed apollo-17 PNG not present")
    # Re-derive the context the build script computes for apollo-17.
    # Apollo-17 has exactly one card so the source label is unambiguous.
    apollo_ctx = FindsOgContext(
        slug="apollo-17",
        title="Apollo 17 Crew Debriefing — What's Actually There",
        subtitle="An exercise in expectation calibration",
        source_label="NASA · 0b298cfc",
        csv_sha256=_load_manifest_sha(),
        status_label="RESEARCH PREVIEW",
    )
    fresh = tmp_path / "apollo-17.png"
    render_finds_og_image(apollo_ctx, fresh)
    assert fresh.read_bytes() == committed.read_bytes(), (
        "apollo-17.png is stale relative to the renderer; "
        "run `python scripts/build_finds_og_images.py` to rebuild"
    )


def _load_manifest_sha() -> str:
    """Read csv_sha256 out of the live manifest the build script uses."""
    import json

    manifest = REPO_ROOT / "data" / "manifests" / "latest.json"
    return json.loads(manifest.read_text())["csv_sha256"]


# --- Smoke test: build all real entries -----------------------------------


def test_all_finds_entries_have_committed_og_images() -> None:
    """The 11 finds entries must each have a committed PNG in
    web/public/og/finds/<slug>.png. A new finds entry without a built
    image will trip this test, prompting the operator to run
    scripts/build_finds_og_images.py."""
    if not FINDS_DIR.exists():
        pytest.skip("finds content dir not present")
    entries = sorted(FINDS_DIR.glob("*.mdx"))
    assert len(entries) > 0, "no finds entries found"
    for mdx in entries:
        png = FINDS_OG_DIR / f"{mdx.stem}.png"
        assert png.exists(), (
            f"missing per-entry OG image for {mdx.stem}; "
            f"run `python scripts/build_finds_og_images.py`"
        )


# --- Astro layout wires per-entry image -----------------------------------


def test_finds_slug_astro_passes_per_entry_og_image() -> None:
    """The /finds/[slug].astro layout must pass an entry-specific
    ``ogImage`` to Base so social scrapers fetch the per-entry PNG."""
    slug_astro = (
        REPO_ROOT / "web" / "src" / "pages" / "finds" / "[slug].astro"
    )
    src = slug_astro.read_text()
    # The layout must pass ogImage referencing /og/finds/<entry.id>.png.
    assert "/og/finds/" in src, (
        "[slug].astro does not pass per-entry ogImage prop"
    )
    assert "ogImage" in src
