"""Run orchestration + coverage gate for the vision stage.

``preflight_coverage`` compares eligible-vs-produced with zero spend — the
verify-before-spend gate the CLI runs by default. ``run_vision`` produces (or
extends) sidecars for eligible items using injected ``examine_fn`` /
``load_image_fn`` seams, so tests drive it without any live API call or PDF
render. The coverage contract is ``produced ⊇ eligible(worklist)``; the report
exposes the shortfall the CLI turns into a non-zero exit.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pursue_index import get_logger
from pursue_index.vision.client import VISION_MODEL
from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.sidecar import build_sidecar, validate_sidecar

log = get_logger(__name__)

Page = tuple[str, int]


@dataclass
class VisionRunReport:
    """Eligible-vs-produced coverage for a vision run."""

    eligible: list[Page]
    produced: list[Page] = field(default_factory=list)

    @property
    def missing(self) -> set[Page]:
        """Eligible pages with no produced sidecar (the shortfall)."""
        return set(self.eligible) - set(self.produced)

    @property
    def ok(self) -> bool:
        """True iff ``produced ⊇ eligible`` — the coverage gate passes."""
        return not self.missing


def produced_pages(out_dir: Path) -> set[Page]:
    """Every ``(card_id, page)`` already present in a sidecar under ``out_dir``.

    Scans ``<card_id>.json`` files (ignoring ``index.json`` and anything
    malformed) so coverage reflects what is genuinely on disk.
    """
    produced: set[Page] = set()
    if not out_dir.exists():
        return produced
    for path in sorted(out_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        card_id = str(data.get("card_id", path.stem))
        for page in data.get("pages", []):
            if isinstance(page, dict) and "page" in page:
                produced.add((card_id, int(page["page"])))
    return produced


def preflight_coverage(items: list[EligibleItem], out_dir: Path) -> VisionRunReport:
    """Report eligible-vs-produced without spending anything."""
    produced = produced_pages(out_dir)
    eligible = [(i.card_id, i.page) for i in items]
    return VisionRunReport(
        eligible=eligible, produced=[p for p in eligible if p in produced]
    )


def _group_by_card(items: list[EligibleItem]) -> "OrderedDict[str, list[EligibleItem]]":
    grouped: OrderedDict[str, list[EligibleItem]] = OrderedDict()
    for item in items:
        grouped.setdefault(item.card_id, []).append(item)
    return grouped


def _examine_new_pages(
    card_items: list[EligibleItem],
    produced: set[Page],
    examine_fn: Callable[[Any], dict[str, Any]],
    load_image_fn: Callable[[EligibleItem], Any],
) -> list[dict[str, Any]]:
    """Examine every not-yet-produced item, returning normalized page dicts."""
    new_pages: list[dict[str, Any]] = []
    for item in card_items:
        if (item.card_id, item.page) in produced:
            continue
        result = dict(examine_fn(load_image_fn(item)))
        result["page"] = item.page
        result.setdefault("observations", [])
        new_pages.append(result)
        produced.add((item.card_id, item.page))
    return new_pages


def _write_card_sidecar(
    path: Path,
    card_id: str,
    title: str,
    new_pages: list[dict[str, Any]],
    model: str,
    session_id: str | None,
) -> None:
    """Write a fresh sidecar or append new pages to an existing one."""
    if path.exists():
        existing = json.loads(path.read_text())
        existing["pages"] = list(existing.get("pages", [])) + new_pages
        validate_sidecar(existing)
        sidecar = existing
    else:
        sidecar = build_sidecar(
            card_id=card_id, title=title, model=model,
            pages=new_pages, session_id=session_id,
        )
    path.write_text(json.dumps(sidecar, indent=2))


def run_vision(
    items: list[EligibleItem],
    out_dir: Path,
    *,
    examine_fn: Callable[[Any], dict[str, Any]],
    load_image_fn: Callable[[EligibleItem], Any],
    model: str = VISION_MODEL,
    session_id: str | None = None,
) -> VisionRunReport:
    """Produce/extend sidecars for eligible ``items``, then report coverage.

    Idempotent: pages already present in a sidecar are skipped (no examine
    call). Sidecars are written to ``out_dir/<card_id>.json``. Returns the
    coverage report recomputed from disk.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = produced_pages(out_dir)
    for card_id, card_items in _group_by_card(items).items():
        new_pages = _examine_new_pages(
            card_items, produced, examine_fn, load_image_fn
        )
        if not new_pages:
            continue
        _write_card_sidecar(
            out_dir / f"{card_id}.json", card_id, card_items[0].title,
            new_pages, model, session_id,
        )
        log.info("vision.card.written", card_id=card_id, pages=len(new_pages))
    return preflight_coverage(items, out_dir)
