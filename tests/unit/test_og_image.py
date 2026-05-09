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

from pursue_index.web import og_fonts
from pursue_index.web.og_fonts import FontLoadError
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


def _count_pixels(
    band: Image.Image,
    *,
    predicate: object,
    step: int = 4,
) -> int:
    """Sample pixels on a stride-``step`` grid and count those matching."""
    n = 0
    for y in range(0, band.height, step):
        for x in range(0, band.width, step):
            r, g, b = band.getpixel((x, y))[:3]
            if predicate(r, g, b):  # type: ignore[operator]
                n += 1
    return n


def test_declassified_stamp_renders_red_pixels(
    tmp_path: Path, ctx: OgImageContext
) -> None:
    """nayru P1 #4 — assert the DECLASSIFIED stamp is actually drawn.
    The stamp is `(212, 49, 58)` red placed in the upper-right quadrant.
    A future refactor that drops ``layers.declassified_stamp(im)`` from
    the orchestrator must fail this test (not only byte-stability)."""
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        # Upper-right quadrant where the rotated stamp lands.
        band = rgb.crop((640, 60, 1200, 320))

        def is_red(r: int, g: int, b: int) -> bool:
            # The stamp red is (212, 49, 58); allow generous slack for
            # antialiasing + alpha knockdown to ~0.78.
            return r > 130 and g < 90 and b < 90

        red = _count_pixels(band, predicate=is_red)
        assert red > 50, f"DECLASSIFIED stamp absent or too sparse: {red} red samples"


def test_footer_status_pill_renders_amber(
    tmp_path: Path, ctx: OgImageContext
) -> None:
    """The footer 'STATUS RESEARCH PREVIEW' label uses ``SIGNAL_AMBER``
    `(255, 200, 87)`. Assert at least a few amber pixels in the footer
    band so a future drop of ``layers.footer_bar`` is caught."""
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((100, 530, 700, 580))

        def is_amber(r: int, g: int, b: int) -> bool:
            # SIGNAL_AMBER (255, 200, 87): high R, mid-high G, low B.
            return r > 220 and g > 150 and b < 130

        amber = _count_pixels(band, predicate=is_amber, step=2)
        assert amber > 20, f"footer status pill absent: {amber} amber samples"


def test_sha256_line_renders_dim_text(
    tmp_path: Path, ctx: OgImageContext
) -> None:
    """The manifest hash line at y=445 prints the sha prefix in
    ``TEXT_DIM`` `(197, 205, 214)`. Assert the band has dim grayish
    text — neither pure white (lockup) nor color highlights."""
    out = tmp_path / "og.png"
    render_og_image(ctx, out)
    with Image.open(out) as im:
        rgb = im.convert("RGB")
        band = rgb.crop((100, 440, 600, 470))

        def is_dim_text(r: int, g: int, b: int) -> bool:
            # TEXT_DIM (197, 205, 214) — near-grey, mid-bright.
            return 150 < r < 230 and 150 < g < 230 and 150 < b < 240 and abs(r - g) < 30

        dim = _count_pixels(band, predicate=is_dim_text, step=2)
        assert dim > 30, f"sha256 line absent: {dim} dim-text samples"


def test_base_astro_validates_ogimage_against_protocol_relative_and_bare() -> None:
    """The ``ogImage`` prop must reject:

    - protocol-relative URLs like ``//cdn.example.com/x.png`` (the old
      ``startsWith("http")`` check let these through and produced
      malformed ``https://pursueindex.com//cdn...`` URLs);
    - bare relative paths missing a leading slash (e.g. ``og.png``);
    - cross-origin absolute URLs that don't begin with ``siteOrigin``
      (SEC-002 — phishing-grade meta-tag injection if a route is ever
      driven by untrusted input).

    Implemented in ``Base.astro`` as a regex test + origin-prefix
    check. We grep for the validator's signature here.
    """
    src = BASE_LAYOUT.read_text()
    # Regex (not bare ``startsWith("http")``) — must match the
    # ``^https?://`` form, not protocol-relative or bare.
    assert "/^https?:\\/\\//" in src or "/^https?:\\/\\//.test(" in src
    # Validator emits a build-time error for invalid shapes so a typo
    # doesn't silently ship a broken og:image meta tag.
    assert "Invalid ogImage" in src or "throw new Error" in src


def test_base_astro_og_url_bound_to_astro_url() -> None:
    """``og:url`` must be derived from ``Astro.url``, not hardcoded —
    a future refactor that fixes it to ``/`` would otherwise pass
    every existing test (vaivora #2). Assert the binding."""
    src = BASE_LAYOUT.read_text()
    assert "Astro.url.pathname" in src
    # canonicalUrl is the variable that flows into og:url and the
    # canonical link.
    assert 'property="og:url" content={canonicalUrl}' in src


def test_base_astro_alt_text_is_consistent_across_og_and_twitter() -> None:
    """nayru P2 #5 — ``og:image:alt`` and ``twitter:image:alt`` must
    use the same alt text so social previews are consistent. We grep
    for a single ``ogImageAlt`` variable bound to both tags."""
    src = BASE_LAYOUT.read_text()
    assert 'property="og:image:alt" content={ogImageAlt}' in src
    assert 'name="twitter:image:alt" content={ogImageAlt}' in src


def test_build_og_image_script_handles_out_path_outside_repo(
    tmp_path: Path,
) -> None:
    """Codex P2 — ``args.out.relative_to(REPO_ROOT)`` raises ``ValueError``
    when the user passes ``--out /tmp/og.png`` (or any absolute path
    outside the repo root). The script must fall back to ``str(args.out)``
    for the success print so successful renders aren't reported as
    failures in CI / local tooling."""
    import subprocess

    out = tmp_path / "og.png"
    repo_root = REPO_ROOT
    result = subprocess.run(
        [
            "python",
            str(repo_root / "scripts" / "build_og_image.py"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"script failed: {result.stderr}"
    assert out.exists()
    # The success line should print *some* path representation, not
    # raise ValueError.
    assert "wrote" in result.stdout
    assert "ValueError" not in result.stderr


def test_deploy_cf_workflow_regenerates_og_image() -> None:
    """vaivora #10 — manifest bumps must not silently drift the OG card.
    The deploy workflow has to call ``build_og_image.py`` as a pre-build
    step so cards/sha updates flow into the rendered PNG automatically.

    Updated for PR #18: the GH-Actions deploy lives at ``deploy-cf.yml``
    (the original ``deploy-ui.yml`` was retired in #18 in favor of the
    Cloudflare Workers fallback workflow)."""
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy-cf.yml"
    text = workflow.read_text()
    assert "build_og_image.py" in text, (
        "deploy-cf.yml does not run scripts/build_og_image.py; the OG "
        "card will silently drift when the manifest updates."
    )
    # Pre-build ordering: regen must run before npm run build (so the
    # PNG is in place when Astro copies web/public into dist/).
    regen_idx = text.index("build_og_image.py")
    npm_build_idx = text.index("npm run build")
    assert regen_idx < npm_build_idx, (
        "OG regen step must run BEFORE 'npm run build' so the fresh "
        "PNG is bundled into the deploy artifact."
    )


def test_build_og_image_script_marks_default_pages_with_todo() -> None:
    """nayru P2 #6 — the placeholder ``DEFAULT_PAGES = 4153`` must
    carry a ``TODO`` marker so it's grep-able once the page-count
    source lands."""
    script = (REPO_ROOT / "scripts" / "build_og_image.py").read_text()
    # Find the DEFAULT_PAGES assignment and assert a TODO is nearby.
    lines = script.splitlines()
    for i, line in enumerate(lines):
        if "DEFAULT_PAGES" in line and "=" in line:
            # Allow TODO on same line or in a comment within 3 lines above.
            window = "\n".join(lines[max(0, i - 3) : i + 1])
            assert "TODO" in window, (
                "DEFAULT_PAGES assignment missing nearby TODO marker; "
                f"context was:\n{window}"
            )
            return
    pytest.fail("DEFAULT_PAGES not found in scripts/build_og_image.py")


def test_mono_raises_when_no_font_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """When all filesystem candidates AND the named lookup fail, the
    font loader must raise ``FontLoadError`` rather than silently
    falling back to PIL's bundled default — that fallback ignores the
    requested size and would produce an unreadable og.png."""
    monkeypatch.setattr(og_fonts, "_first_existing", lambda paths: None)

    def _always_fail(*_: object, **__: object) -> object:  # pragma: no cover
        raise OSError("simulated: no truetype available")

    monkeypatch.setattr(og_fonts.ImageFont, "truetype", _always_fail)
    with pytest.raises(FontLoadError):
        og_fonts.mono(96, bold=True)


def test_sans_raises_when_no_font_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same contract as ``mono`` — never silently degrade to the bundled
    default size."""
    monkeypatch.setattr(og_fonts, "_first_existing", lambda paths: None)

    def _always_fail(*_: object, **__: object) -> object:  # pragma: no cover
        raise OSError("simulated: no truetype available")

    monkeypatch.setattr(og_fonts.ImageFont, "truetype", _always_fail)
    with pytest.raises(FontLoadError):
        og_fonts.sans(30)
