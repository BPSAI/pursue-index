"""DOM extraction for PURSUE cards.

The DOW page is JS-rendered, so selectors are tuned against the live runtime DOM
rather than the SSR HTML. Selector constants live at the top of this module to
make them easy to update when the page changes (and it will).

Strategy:
  1. Wait for the card grid to render.
  2. Iterate pagination (1..N).
  3. For each card, capture card-level metadata directly.
  4. Open the modal, capture description + PDF URL, close.
  5. Build a ``CardMetadata`` for each.

If selectors are wrong, ``inspect_dom`` can be used in inspect-mode to dump the
rendered HTML for analysis without committing to extraction.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import Locator, Page

from pursue_index import get_logger
from pursue_index.scrape.types import CardMetadata

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Selectors (tune against live DOM via `pursue scrape inspect`)
# ---------------------------------------------------------------------------
SEL_CARD_GRID = '[data-cards], .cards-grid, table tbody'
SEL_CARD = '[data-card], tr.card-row, .card'
SEL_PAGINATION_NEXT = 'button[aria-label="Next page"], [data-pagination-next]'
SEL_PAGINATION_PAGE_INDICATOR = '[data-pagination-current], .pagination-current'

SEL_MODAL = '[role="dialog"], .modal[aria-modal="true"]'
SEL_MODAL_CLOSE = '[role="dialog"] [aria-label="Close"], .modal [data-close]'
SEL_MODAL_TITLE = '[role="dialog"] h1, [role="dialog"] h2, .modal-title'
SEL_MODAL_DESCRIPTION = '[role="dialog"] .description, [role="dialog"] p'
SEL_MODAL_DOWNLOAD_LINK = '[role="dialog"] a[href$=".pdf"]'

# Card field labels on the page (we'll look for these as adjacent label/value pairs)
FIELD_LABELS = {
    "agency": "Agency",
    "release_date": "Release Date",
    "incident_date": "Incident Date",
    "incident_location": "Incident Location",
    "case_type": "Type",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def inspect_dom(page: Page) -> str:
    """Return the rendered HTML of the page. Used to tune selectors offline."""
    await page.wait_for_load_state("networkidle")
    return await page.content()


async def extract_all_cards(page: Page, *, max_pages: int | None = None) -> list[CardMetadata]:
    """Walk pagination and collect every card.

    Args:
        page: Playwright page already navigated to the source URL.
        max_pages: Cap pagination for testing. ``None`` means walk to the end.
    """
    await page.wait_for_load_state("networkidle")

    cards: list[CardMetadata] = []
    page_idx = 1

    while True:
        if max_pages is not None and page_idx > max_pages:
            break

        log.info("scrape.page", page=page_idx)
        page_cards = await _extract_cards_on_page(page)
        log.info("scrape.page.extracted", page=page_idx, count=len(page_cards))
        cards.extend(page_cards)

        # Try to advance pagination; break if we can't
        next_btn = page.locator(SEL_PAGINATION_NEXT).first
        if not await _is_clickable(next_btn):
            log.info("scrape.pagination.end", final_page=page_idx)
            break
        await next_btn.click()
        await page.wait_for_load_state("networkidle")
        page_idx += 1

    return cards


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
async def _is_clickable(loc: Locator) -> bool:
    try:
        return await loc.is_visible() and await loc.is_enabled()
    except Exception:
        return False


async def _extract_cards_on_page(page: Page) -> list[CardMetadata]:
    """Extract every card currently rendered on the page."""
    grid = page.locator(SEL_CARD_GRID).first
    await grid.wait_for(state="visible")

    card_locs = page.locator(SEL_CARD)
    count = await card_locs.count()
    out: list[CardMetadata] = []

    for i in range(count):
        card = card_locs.nth(i)
        try:
            meta = await _extract_one_card(page, card)
            out.append(meta)
        except Exception as exc:
            log.warning("scrape.card.failed", index=i, error=str(exc))

    return out


async def _extract_one_card(page: Page, card: Locator) -> CardMetadata:
    """Pull metadata from a single card, opening its modal for the PDF URL."""
    # Card-level fields (visible without opening modal)
    fields = await _extract_card_fields(card)

    # Open modal
    await card.click()
    modal = page.locator(SEL_MODAL).first
    await modal.wait_for(state="visible")

    # Modal-level fields
    title = await _safe_text(modal.locator(SEL_MODAL_TITLE).first)
    description = await _safe_text(modal.locator(SEL_MODAL_DESCRIPTION).first)
    pdf_link = modal.locator(SEL_MODAL_DOWNLOAD_LINK).first
    pdf_url_raw = await pdf_link.get_attribute("href") or ""
    pdf_url = urljoin(str(page.url), pdf_url_raw)

    # Close modal
    close = modal.locator(SEL_MODAL_CLOSE).first
    if await _is_clickable(close):
        await close.click()
    else:
        await page.keyboard.press("Escape")
    await modal.wait_for(state="hidden")

    pdf_filename = _filename_from_url(pdf_url)
    card_id = _stable_id(pdf_url)

    return CardMetadata(
        card_id=card_id,
        pdf_url=pdf_url,
        pdf_filename=pdf_filename,
        agency=fields.get("agency"),
        release_date=fields.get("release_date"),
        incident_date=fields.get("incident_date"),
        incident_location=fields.get("incident_location"),
        type=fields.get("case_type"),
        title=title,
        description=description,
    )


async def _extract_card_fields(card: Locator) -> dict[str, str | None]:
    """Pull the labelled fields off a card.

    Falls back to whole-card text parsing if the card doesn't expose discrete
    labelled elements. Tune this when the real DOM is known.
    """
    text = (await card.inner_text()) or ""
    out: dict[str, str | None] = {}
    for key, label in FIELD_LABELS.items():
        out[key] = _grab_labeled_value(text, label)
    return out


def _grab_labeled_value(text: str, label: str) -> str | None:
    """Best-effort: find ``Label: value`` or ``Label\\nvalue`` patterns."""
    pattern = rf"{re.escape(label)}\s*[:\n]\s*([^\n]+)"
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip() or None


async def _safe_text(loc: Locator) -> str | None:
    try:
        if await loc.count() == 0:
            return None
        return (await loc.inner_text()).strip() or None
    except Exception:
        return None


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path.rsplit("/", 1)[-1] or "unknown.pdf"


def _stable_id(pdf_url: str) -> str:
    """Deterministic id derived from the PDF URL — survives re-scrapes."""
    return hashlib.sha256(pdf_url.encode("utf-8")).hexdigest()[:16]
