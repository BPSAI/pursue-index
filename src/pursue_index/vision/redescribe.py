"""``pursue vision run --redescribe``: re-examine pages that already have a pass.

``run_vision`` examines only *eligible* items (IMG assets, image-only PDF pages)
and skips anything a sidecar already covers. A re-describe is the opposite
question: for the listed cards, take exactly the pages their existing sidecars
describe — whatever kind of page, whether or not it carries OCR text — and
examine them again with the pinned model.

The result *supersedes* rather than overwrites. The sidecar's previous
``our_pass`` and ``pages`` are appended to ``superseded_passes`` (an earlier
entry is never dropped), the new pass and pages take the live positions, and
every other key — the curated ones — is carried over untouched.

A card is replaced only when *every* one of its pages was re-examined with
content. A card the budget, a failure or an empty reply cut short is left
byte-for-byte as it was, so a partial re-description can never displace a
complete one.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pursue_index import get_logger
from pursue_index.download.downloader import asset_path_for
from pursue_index.scrape.types import Manifest
from pursue_index.vision.client import VISION_MODEL
from pursue_index.vision.eligibility import CoverageKey, EligibleItem, keyed_rows
from pursue_index.vision.run import ESTIMATED_COST_PER_CALL_USD, VisionRunReport, _examine_one
from pursue_index.vision.sidecar import page_has_content, validate_sidecar
from pursue_index.vision.spend import SpendBudget, rates_for, worst_case_call_usd

log = get_logger(__name__)

METHOD = "vision-run"
_DEFAULT_CONTEXT = "vision-observation-generator"
# A typical call, for the no-spend preflight's estimate only: one image
# (<= ~1,600 input tokens) and a ~800-token description. The spend gate never
# uses this; it enforces the worst case (``vision.spend.worst_case_call_usd``).
_TYPICAL_INPUT_TOKENS = 1_600
_TYPICAL_OUTPUT_TOKENS = 800


@dataclass
class RedescribePlan:
    """What a re-describe would examine, and what stops it from starting."""

    items_by_card: OrderedDict[str, list[EligibleItem]] = field(default_factory=OrderedDict)
    refusals: list[str] = field(default_factory=list)

    @property
    def card_count(self) -> int:
        return len(self.items_by_card)

    @property
    def page_count(self) -> int:
        return sum(len(v) for v in self.items_by_card.values())

    @property
    def keys(self) -> list[CoverageKey]:
        return [i.coverage_key for v in self.items_by_card.values() for i in v]


def estimate_cost_usd(page_count: int, model: str = VISION_MODEL) -> float:
    """Typical-call cost of ``page_count`` pages (an estimate, not a cap)."""
    r = rates_for(model)
    per_call = (_TYPICAL_INPUT_TOKENS * r.input + _TYPICAL_OUTPUT_TOKENS * r.output) / 1_000_000
    return page_count * per_call


def worst_case_usd(page_count: int, model: str = VISION_MODEL) -> float:
    return page_count * worst_case_call_usd(model)


def _read_sidecar(path: Path) -> dict[str, Any] | str:
    """The parsed sidecar, or the reason it cannot be re-described."""
    if not path.exists():
        return "no existing sidecar — use --run for a card that has not been described"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"existing sidecar is not valid JSON ({exc})"
    if not isinstance(data, dict):
        return "existing sidecar is not a JSON object"
    return data


def _items_for_sidecar(
    card_id: str, sidecar: dict[str, Any], rows: dict[str, Any]
) -> tuple[list[EligibleItem], list[str]]:
    """One item per page the sidecar describes, plus any reasons one cannot be built."""
    items: list[EligibleItem] = []
    problems: list[str] = []
    for page in sidecar.get("pages", []):
        if not isinstance(page, dict) or "page" not in page:
            continue
        number = int(page["page"])
        row_key = str(page.get("row_key", "") or "")
        row = rows.get(row_key)
        path = asset_path_for(row) if row is not None else None
        if row is None or path is None:
            why = "no manifest row" if row is None else "no asset bytes"
            problems.append(f"{card_id} p{number}: {why} for row {row_key!r}")
            continue
        items.append(EligibleItem(
            card_id=card_id, page=number,
            kind="img_card" if row.asset_type == "IMG" else "image_only_page",
            image_path=path, title=row.title, row_key=row_key,
        ))
    if not items and not problems:
        problems.append(f"{card_id}: existing sidecar describes no pages")
    return items, problems


def plan_redescribe(manifest: Manifest, card_ids: set[str], out_dir: Path) -> RedescribePlan:
    """Resolve the listed cards to exactly the pages their sidecars describe.

    Nothing here spends. Any card that cannot be re-described — no sidecar, not
    in the manifest, a page with no backing row — lands in ``refusals`` so the
    caller can refuse the whole invocation before a single call.
    """
    plan = RedescribePlan()
    rows_by_card = keyed_rows(manifest, card_ids)
    for card_id in sorted(card_ids):
        sidecar = _read_sidecar(out_dir / f"{card_id}.json")
        if isinstance(sidecar, str):
            plan.refusals.append(f"{card_id}: {sidecar}")
            continue
        rows = rows_by_card.get(card_id)
        if not rows:
            plan.refusals.append(f"{card_id}: not an IMG/PDF card in the manifest")
            continue
        items, problems = _items_for_sidecar(card_id, sidecar, rows)
        plan.refusals.extend(problems)
        if items and not problems:
            plan.items_by_card[card_id] = items
    return plan


def supersede_sidecar(
    existing: dict[str, Any], new_pages: list[dict[str, Any]], *,
    model: str, now: str,
) -> dict[str, Any]:
    """``existing`` with a new pass in front and the old one kept, not dropped.

    Key order is preserved (the new values take the old keys' places), so the
    diff of a re-described file is the pass, the pages and one new key.
    """
    old_pass = existing.get("our_pass") or {}
    superseded = list(existing.get("superseded_passes") or [])
    superseded.append({
        "our_pass": old_pass, "pages": existing.get("pages", []), "superseded_at": now,
    })
    new = dict(existing)
    new["our_pass"] = {
        "model": model, "method": METHOD,
        "context": old_pass.get("context", _DEFAULT_CONTEXT), "described_at": now,
    }
    new["pages"] = new_pages
    new["superseded_passes"] = superseded
    validate_sidecar(new)
    return new


def _write_atomic(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(path)


def _examine_card(
    card_items: list[EligibleItem],
    examine_fn: Callable[[Any], dict[str, Any]],
    load_image_fn: Callable[[EligibleItem], Any],
    budget: SpendBudget | None,
    failures: list[tuple[CoverageKey, str]],
    empty: list[CoverageKey],
) -> tuple[list[dict[str, Any]] | None, bool]:
    """Re-examine every page of one card; ``None`` pages when it is incomplete.

    The second value is True when the budget stopped the run.
    """
    pages: list[dict[str, Any]] = []
    complete = True
    for item in card_items:
        if budget is not None:
            if not budget.can_start():
                return None, True
            budget.reserve()
        try:
            result = _examine_one(item, examine_fn, load_image_fn, budget)
        except Exception as exc:  # one page's trouble is its own
            failures.append((item.coverage_key, f"{type(exc).__name__}: {exc}"))
            log.warning("vision.redescribe.item_failed", card_id=item.card_id,
                        page=item.page, error=str(exc))
            complete = False
            continue
        result["page"] = item.page
        result["row_key"] = item.row_key
        if not page_has_content(result):
            empty.append(item.coverage_key)
            complete = False
            continue
        pages.append(result)
    return (pages if complete else None), False


def redescribe_vision(
    plan: RedescribePlan,
    out_dir: Path,
    *,
    examine_fn: Callable[[Any], dict[str, Any]],
    load_image_fn: Callable[[EligibleItem], Any],
    model: str = VISION_MODEL,
    budget_usd: float,
    cost_per_item_usd: float = ESTIMATED_COST_PER_CALL_USD,
    worst_case_item_usd: float | None = None,
) -> VisionRunReport:
    """Re-examine every planned page and supersede each fully-described card."""
    budget = SpendBudget(budget_usd, model, cost_per_item_usd, worst_case_item_usd)
    failures: list[tuple[CoverageKey, str]] = []
    empty: list[CoverageKey] = []
    produced: list[CoverageKey] = []
    now = datetime.now(UTC).isoformat()
    for card_id, card_items in plan.items_by_card.items():
        pages, exhausted = _examine_card(
            card_items, examine_fn, load_image_fn, budget, failures, empty
        )
        if pages is not None:
            path = out_dir / f"{card_id}.json"
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                _write_atomic(path, supersede_sidecar(existing, pages, model=model, now=now))
            except Exception as exc:  # one card's trouble is its own
                reason = f"{type(exc).__name__}: {exc}"
                failures.extend((i.coverage_key, reason) for i in card_items)
                log.warning("vision.redescribe.not_written", card_id=card_id, error=str(exc))
            else:
                produced.extend(i.coverage_key for i in card_items)
                log.info("vision.redescribe.written", card_id=card_id, pages=len(pages))
        if exhausted:
            break
    return VisionRunReport(
        eligible=plan.keys, produced=produced, failures=failures, empty=empty,
        spent_usd=budget.spent_usd,
    )
