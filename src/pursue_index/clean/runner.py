"""Per-card cleanup runner.

Reads ``pages.jsonl``, cleans each unseen page via the Anthropic client,
writes per-row provenance to ``pages_cleaned.jsonl``, and respects a hard
USD budget cap that aborts mid-card if exceeded.

Idempotency contract: a sidecar row whose ``input_sha256`` matches the
new input's hash is skipped. Switching model or prompt invalidates the
skip (the runner re-keys via ``idempotency_key``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pursue_index import get_logger
from pursue_index.clean import sidecar as clean_sidecar
from pursue_index.clean.client import (
    ContentFilteredError,
    Usage,
    clean_page,
    estimate_cost_usd,
)
from pursue_index.clean.prompt import (
    input_sha256,
    prompt_sha256,
)

log = get_logger(__name__)


# Length-divergence guard: cleaned output outside [0.2x, 2.0x] of the raw
# input is implausible for "fix OCR errors only" — refusal / preamble
# leak / silent drop. Fall back to raw.
_LENGTH_RATIO_MIN = 0.2
_LENGTH_RATIO_MAX = 2.0


class BudgetExceededError(RuntimeError):
    """Raised when the cumulative cost crosses the configured cap.

    The runner raises mid-card so partial work is preserved (the sidecar
    is appended row-by-row, so the next ``run_card`` call resumes cleanly
    via the idempotency check).

    Carries ``partial_cost_usd`` (the spend on the in-progress card
    before the cap tripped), ``card_id``, and ``pages_cleaned`` so the
    CLI can fold the partial spend into the printed summary. Without
    these, the summary under-reports total spend by the partial-card
    amount and the operator may overspend on the next invocation.
    """

    def __init__(
        self,
        message: str,
        *,
        partial_cost_usd: float = 0.0,
        card_id: str = "",
        pages_cleaned: int = 0,
    ) -> None:
        super().__init__(message)
        self.partial_cost_usd = partial_cost_usd
        self.card_id = card_id
        self.pages_cleaned = pages_cleaned


@dataclass
class CardReport:
    """Per-card outcome stats — fed to the pilot run summary."""

    card_id: str
    pages_cleaned: int
    pages_skipped: int
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int


def _length_diverges(raw_text: str, cleaned_text: str) -> bool:
    """True when the cleaned-output length is implausibly off the raw."""
    ratio = len(cleaned_text) / max(len(raw_text), 1)
    return ratio < _LENGTH_RATIO_MIN or ratio > _LENGTH_RATIO_MAX


def _accumulate_usage(totals: list[Usage], one: Usage) -> None:
    """Add ``one`` into the rolling total at ``totals[0]`` (in-place).

    Side-effect-only: callers read the running total via ``totals[0]``
    after the call (the 1-elem list is just a closure trick to dodge
    Python's name-binding rules). The prior signature returned the new
    total, but the only caller discarded it; trimmed the return so the
    contract reads honestly.
    """
    prev = totals[0]
    totals[0] = Usage(
        input_tokens=prev.input_tokens + one.input_tokens,
        output_tokens=prev.output_tokens + one.output_tokens,
        cache_read_tokens=prev.cache_read_tokens + one.cache_read_tokens,
        cache_creation_tokens=prev.cache_creation_tokens + one.cache_creation_tokens,
    )


def _call_cost(usage: Usage) -> float:
    """Wrapper so the per-page loop reads as a one-liner."""
    return estimate_cost_usd(
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
    )


def _clean_one_page(
    *,
    card_id: str, page: int, raw_text: str,
    model_id: str, prompt_sha: str,
    sidecar_path: Path, totals: list[Usage],
) -> float:
    """Clean one page, write its sidecar row, return the call's USD cost."""
    cleaned_text, usage = clean_page(raw_text=raw_text, model_id=model_id)
    _accumulate_usage(totals, usage)
    cleanup_skipped: str | None = None
    if _length_diverges(raw_text, cleaned_text):
        log.warning(
            "clean.page.length_divergence",
            card_id=card_id, page=page,
            raw_len=len(raw_text), cleaned_len=len(cleaned_text),
            ratio=round(len(cleaned_text) / max(len(raw_text), 1), 3),
        )
        cleaned_text = raw_text
        cleanup_skipped = "length_divergence"
    sidecar_row = clean_sidecar.row_from_clean(
        card_id=card_id,
        page=page,
        cleaned_text=cleaned_text,
        raw_text=raw_text,
        model_id=model_id,
        prompt_sha=prompt_sha,
        cleanup_skipped=cleanup_skipped,
    )
    clean_sidecar.write_row(sidecar_path, sidecar_row)
    return _call_cost(usage)


@dataclass
class _CardLoopState:
    """Mutable accumulator for the per-page loop. Internal only.

    ``start_cost`` is the running total at card entry — used to compute
    partial-card spend when the budget cap trips mid-card.
    """

    cost: float
    start_cost: float
    cleaned: int = 0
    skipped: int = 0


def _write_skip_row(
    *,
    sidecar_path: Path, card_id: str, page: int, raw_text: str,
    model_id: str, prompt_sha: str, reason: str,
) -> None:
    """Append a ``cleanup_skipped`` sidecar row with empty cleaned text.

    Shared helper for the three skip cases (``empty_input``,
    ``content_filter``, and — historically — ``length_divergence``,
    which still routes through ``_clean_one_page`` because it requires
    inspecting the model's reply). Keeping the row shape identical
    across skip reasons lets the build script's
    ``_sanitize_row_for_mirror`` treat them uniformly.
    """
    row = clean_sidecar.row_from_clean(
        card_id=card_id, page=page, cleaned_text="", raw_text=raw_text,
        model_id=model_id, prompt_sha=prompt_sha,
        cleanup_skipped=reason,
    )
    clean_sidecar.write_row(sidecar_path, row)


def _try_clean_or_skip(
    *,
    card_id: str, page: int, raw_text: str, model_id: str, prompt_sha: str,
    sidecar_path: Path, totals: list[Usage], state: _CardLoopState,
) -> None:
    """Run ``_clean_one_page`` with content-filter fallback.

    Catches ``ContentFilteredError`` so a single rejected page does not
    crash the whole pilot mid-card (the bug that took down card
    ``7d58f0cac741650a`` page 88). Writes a ``content_filter`` skip row
    and continues. No cost is added: filter rejections are not billed
    by Anthropic (the API rejects before returning output).
    """
    try:
        state.cost += _clean_one_page(
            card_id=card_id, page=page, raw_text=raw_text,
            model_id=model_id, prompt_sha=prompt_sha,
            sidecar_path=sidecar_path, totals=totals,
        )
        state.cleaned += 1
    except ContentFilteredError as exc:
        # Bind request_id at the runner site so the per-card-page
        # correlation (card_id, page) ↔ Anthropic request_id lives in a
        # single log scope. The client already emits
        # ``clean.llm.content_filtered`` at the SDK boundary; this
        # runner-site warning gives operator post-mortems all the
        # context they need without having to join across log streams.
        log.warning(
            "clean.page.content_filtered",
            card_id=card_id, page=page,
            request_id=exc.request_id,
        )
        _write_skip_row(
            sidecar_path=sidecar_path, card_id=card_id, page=page,
            raw_text=raw_text, model_id=model_id, prompt_sha=prompt_sha,
            reason="content_filter",
        )
        state.skipped += 1


def _process_page(
    *,
    row: dict, existing: dict[int, dict], card_id: str,
    model_id: str, prompt_sha: str, sidecar_path: Path,
    totals: list[Usage], state: _CardLoopState, budget_usd: float,
) -> None:
    """Handle one input row: skip-or-clean, update state, enforce budget."""
    page = int(row.get("page", 0))
    raw_text = str(row.get("text", ""))
    prior = existing.get(page)
    if prior is not None and clean_sidecar.should_skip(
        prior, input_sha256(raw_text),
        new_model_id=model_id, new_prompt_sha=prompt_sha,
    ):
        state.skipped += 1
        return
    # Empty raw OCR is empty-in/empty-out — skip the model call
    # and record a clean-flagged row for provenance. Calling the model on
    # an empty payload would trip the length-divergence guard with
    # misleading provenance ("length_divergence" reads like a refusal).
    if not raw_text.strip():
        _write_skip_row(
            sidecar_path=sidecar_path, card_id=card_id, page=page,
            raw_text=raw_text, model_id=model_id, prompt_sha=prompt_sha,
            reason="empty_input",
        )
        state.skipped += 1
        return
    _try_clean_or_skip(
        card_id=card_id, page=page, raw_text=raw_text,
        model_id=model_id, prompt_sha=prompt_sha,
        sidecar_path=sidecar_path, totals=totals, state=state,
    )
    log.info("clean.page.done", card_id=card_id, page=page,
             running_cost_usd=round(state.cost, 4))
    if state.cost > budget_usd:
        raise BudgetExceededError(
            f"Cost cap ${budget_usd:.2f} exceeded after page {page} "
            f"of card {card_id} (running ${state.cost:.4f}). Sidecar "
            f"preserved; re-run to resume.",
            partial_cost_usd=state.cost - state.start_cost,
            card_id=card_id,
            pages_cleaned=state.cleaned,
        )


def run_card(
    *,
    card_id: str,
    pages_path: Path,
    sidecar_path: Path,
    model_id: str,
    budget_usd: float,
    running_cost_usd: float,
) -> CardReport:
    """Clean every uncached page in ``pages_path`` to ``sidecar_path``.

    Raises ``BudgetExceededError`` if the running total (passed in plus
    this run's accumulated cost) crosses ``budget_usd``.
    """
    rows_in = clean_sidecar.read_pages(pages_path)
    existing = clean_sidecar.load_existing(sidecar_path)
    prompt_sha = prompt_sha256()
    totals: list[Usage] = [Usage(0, 0, 0, 0)]
    state = _CardLoopState(cost=running_cost_usd, start_cost=running_cost_usd)
    for row in rows_in:
        _process_page(
            row=row, existing=existing, card_id=card_id, model_id=model_id,
            prompt_sha=prompt_sha, sidecar_path=sidecar_path, totals=totals,
            state=state, budget_usd=budget_usd,
        )
    return CardReport(
        card_id=card_id,
        pages_cleaned=state.cleaned,
        pages_skipped=state.skipped,
        cost_usd=state.cost - running_cost_usd,
        input_tokens=totals[0].input_tokens,
        output_tokens=totals[0].output_tokens,
        cache_read_tokens=totals[0].cache_read_tokens,
    )
