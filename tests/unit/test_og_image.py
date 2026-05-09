"""Test the OG image builder.

The build script must:

1. Produce a 1200x630 PNG (Open Graph spec / Twitter summary_large_image).
2. Stay under 200 KB so HN/Reddit/Twitter scrapers don't bail on size.
3. Be idempotent: same inputs => same byte-stable output (so re-running
   in CI doesn't churn ``web/public/og.png``).
4. Render legibly at 600x315 (Slack default thumbnail) — we verify by
   asserting the lockup occupies a substantial vertical band of the image
   so it doesn't disappear when downscaled.

Snapshot-style test on the Astro layout asserts the OG/Twitter meta
tags are present and reference the canonical host. No JS test framework
in the web package, so we grep the source.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pursue_index.web.og_image import OgImageContext, render_og_image

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_LAYOUT = REPO_ROOT / "web" / "src" / "layouts" / "Base.astro"


@pytest.fixture
def ctx() -> OgImageContext:
    """Stable inputs so the test is deterministic across machines."""
    return OgImageContext(
        cards=161,
        pages=4153,
        csv_sha256="596cc1881aa97d2fa49a45edab14d60802616e73ce125d286120e00d967cafa2",
        source_host="war.gov",
        status_label="RESEARCH PREVIEW",
    )


def test_render_produces_correct_dimensions(tmp_path: Path, ctx: OgImageContext) -> None:
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    with Image.open(out) as im:
        assert im.size == (1200, 630)
        assert im.format == "PNG"


def test_render_under_200kb(tmp_path: Path, ctx: OgImageContext) -> None:
    """Under 200 KB so social scrapers don't reject; many cap at 1 MB but
    smaller is faster on the unfurl path."""
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    assert out.stat().st_size < 200 * 1024


def test_render_is_byte_stable(tmp_path: Path, ctx: OgImageContext) -> None:
    """Two renders with identical inputs must produce identical bytes
    so CI doesn't churn the committed PNG. PIL embeds no timestamps when
    we strip metadata, but we assert it explicitly here."""
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    render_og_image(ctx, a)
    render_og_image(ctx, b)
    assert a.read_bytes() == b.read_bytes()


def test_lockup_occupies_substantial_vertical_band(
    tmp_path: Path, ctx: OgImageContext
) -> None:
    """At 600x315 thumbnail size, the PURSUE://INDEX lockup must remain
    legible. Verify the lockup band (y=180..320 in source coords)
    contains a meaningful number of bright pixels — i.e. the title is
    actually drawn there, not blank."""
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    with Image.open(out) as im:
        # Sample the lockup band; bright pixels = drawn glyphs / accents.
        rgb = im.convert("RGB")
        band = rgb.crop((80, 180, 1120, 320))
        bright = 0
        # Sample on a grid to keep the test fast.
        for y in range(0, band.height, 4):
            for x in range(0, band.width, 4):
                r, g, b_ = band.getpixel((x, y))
                if r + g + b_ > 300:  # roughly "not background"
                    bright += 1
        assert bright > 200, f"lockup band too sparse: {bright} bright samples"


def test_base_astro_head_has_og_meta_tags() -> None:
    """The Base layout must emit a complete OG + Twitter card header so
    HN/Reddit/Twitter/Mastodon/Bluesky all unfurl correctly."""
    src = BASE_LAYOUT.read_text()
    expected = [
        'property="og:type"',
        'property="og:title"',
        'property="og:description"',
        'property="og:url"',
        'property="og:image"',
        'property="og:image:width"',
        'property="og:image:height"',
        'property="og:image:type"',
        'property="og:image:alt"',
        'name="twitter:card"',
        'content="summary_large_image"',
        'name="twitter:title"',
        'name="twitter:image"',
    ]
    for tag in expected:
        assert tag in src, f"Base.astro missing meta tag: {tag}"


def test_base_astro_uses_absolute_og_image_url() -> None:
    """og:image must be absolute — Twitter/Slack/Bluesky scrapers do not
    resolve relative URLs. The layout builds this from ``Astro.site`` /
    ``siteOrigin`` so it's always prefixed with ``https://...``."""
    src = BASE_LAYOUT.read_text()
    # ogImageUrl is built from siteOrigin which falls back to
    # https://pursueindex.com — the literal must appear so even with no
    # Astro.site config the URL is absolute.
    assert "https://pursueindex.com" in src
    # The og:image meta tag must use the computed absolute URL var.
    assert 'content={ogImageUrl}' in src


def test_per_route_og_image_override_supported() -> None:
    """Pages must be able to pass their own ``ogImage`` prop and have it
    win over the default ``/og.png``."""
    src = BASE_LAYOUT.read_text()
    assert "ogImage?: string" in src
    # The fallback path: if ogImage is set, use it; else default to /og.png.
    assert "/og.png" in src
