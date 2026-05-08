"""Playwright lifecycle wrapper for scraping the PURSUE index."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import async_playwright

from pursue_index.config import settings
from pursue_index import get_logger
from pursue_index.scrape.extractor import extract_all_cards, inspect_dom
from pursue_index.scrape.types import Manifest

log = get_logger(__name__)


class PlaywrightRunner:
    """Drives Playwright for both inspect and run flows."""

    def __init__(
        self,
        *,
        headless: bool | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        self.headless = headless if headless is not None else settings.scrape_headless
        self.timeout_ms = timeout_ms or settings.scrape_timeout_ms

    async def inspect(self, out_dir: Path) -> Path:
        """Save the rendered DOM to disk for offline selector tuning."""
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"war-gov-ufo-{timestamp}.html"
        screenshot_path = out_dir / f"war-gov-ufo-{timestamp}.png"

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(user_agent=settings.scrape_user_agent)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            log.info("inspect.navigate", url=str(settings.source_url))
            await page.goto(str(settings.source_url))
            html = await inspect_dom(page)
            out_path.write_text(html, encoding="utf-8")
            await page.screenshot(path=str(screenshot_path), full_page=True)
            log.info("inspect.saved", html=str(out_path), screenshot=str(screenshot_path))

            await browser.close()

        return out_path

    async def run(self, *, max_pages: int | None = None) -> Manifest:
        """Walk the index, returning a fully-populated Manifest."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(user_agent=settings.scrape_user_agent)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            log.info("scrape.navigate", url=str(settings.source_url))
            await page.goto(str(settings.source_url))

            cards = await extract_all_cards(page, max_pages=max_pages)
            log.info("scrape.complete", card_count=len(cards))

            await browser.close()

        return Manifest(
            source_url=settings.source_url,
            scraped_at=datetime.now(UTC),
            cards=cards,
        )
