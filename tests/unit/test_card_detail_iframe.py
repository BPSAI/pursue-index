"""Static contract tests for the card-detail page's PDF iframe source.

Background: in May 2026, war.gov / Akamai added cross-origin framing
protection (``X-Frame-Options`` / ``frame-ancestors``) which broke the
in-page iframe embed of corpus PDFs while leaving direct opens working.
We mirror the corpus into the Cloudflare R2 bucket ``pursue-pdfs`` and
serve the PDFs from a same-origin Worker route at ``/pdf/<card_id>.pdf``;
the OPEN ↗ button still points at war.gov as the citation source.

These tests are intentionally a string grep against the Astro page rather
than a render-time assertion. We don't run Astro in pytest, but the iframe
``src`` is load-bearing — if a future refactor flips the iframe back to
``card.asset_url`` the framing block returns and the page silently breaks
again. A grep is cheap insurance against that regression.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CARD_DETAIL_PATH = REPO_ROOT / "web" / "src" / "pages" / "card" / "[card_id].astro"


def _read_card_detail() -> str:
    return CARD_DETAIL_PATH.read_text(encoding="utf-8")


def test_iframe_src_points_at_self_hosted_pdf_route() -> None:
    """The iframe must load from the same-origin /pdf/<id>.pdf route."""
    src = _read_card_detail()
    # Allow either backtick template literals or string concat, but the
    # route prefix must appear AND be applied to the iframe element.
    assert "/pdf/" in src, (
        "card detail page must reference the self-hosted /pdf/ route"
    )
    # The iframe element id is stable; co-locate it with the route so a
    # refactor that splits the iframe out still trips this assertion.
    assert 'id="card-pdf-iframe"' in src
    # Quick proxy for "iframe src derives from card_id, not asset_url":
    # the literal pattern `/pdf/${card.card_id}.pdf` should appear.
    assert "/pdf/${card.card_id}.pdf" in src


def test_iframe_src_does_not_point_at_war_gov_directly() -> None:
    """Regression: the iframe.src must not be the war.gov URL anymore.

    The OPEN ↗ button still uses ``card.asset_url`` (citation source),
    but the iframe must not — that's what triggered the framing block.
    """
    src = _read_card_detail()
    # Find the iframe block (between `<iframe` and `></iframe>`).
    start = src.find("<iframe")
    end = src.find("></iframe>", start)
    assert start != -1 and end != -1, "card detail page must contain an iframe"
    iframe_block = src[start:end]
    assert "card.asset_url" not in iframe_block, (
        "iframe src must not be card.asset_url — that triggers the war.gov "
        "framing block. Use the self-hosted /pdf/ route."
    )


def test_open_button_still_uses_war_gov_asset_url() -> None:
    """The OPEN ↗ button is the citation link; war.gov stays the cite-of-record.

    This is the *complement* of the iframe test: we changed only the iframe
    src, not the OPEN button. If a future refactor accidentally points the
    OPEN button at the R2 mirror, we lose the war.gov citation contract.
    """
    src = _read_card_detail()
    # OPEN ↗ link signature: anchor with target="_blank" + href={card.asset_url}.
    assert "OPEN ↗" in src
    assert "href={card.asset_url}" in src
