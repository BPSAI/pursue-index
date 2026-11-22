"""Metered spend for the vision stage's ``--live --budget-usd`` cap.

A cap is only a cap if it is checked against what calls really cost. This
module prices a response from the usage it reports, at the model's rates, and
decides whether the next call may start: it may only when the *worst* a call
can cost still fits in what is left. The flat per-call estimate survives only
as the pre-call reservation; once the response arrives, its real cost replaces
the reservation. A response that reports no usage is charged its worst case,
so a missing number can never make the run cheaper than it was.

The worst case is built the way ``release.rates`` builds its worst case: one
image resized to a 1568px long edge (<= ~1,600 input tokens), a system prompt
under 1,000 tokens, every input token at the cache-write premium, and the
request's full ``max_tokens=2048`` of output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pursue_index.release.rates import CACHE_WRITE_MULTIPLE, WORST_CASE_IMAGE_INPUT_TOKENS

_M = 1_000_000
_MAX_OUTPUT_TOKENS = 2_048  # vision.client._build_request max_tokens
# The image/prompt token ceiling and cache-write premium are Anthropic-billing
# facts shared with the OCR rates table; only the per-model rate is local here.
_WORST_CASE_INPUT_TOKENS = WORST_CASE_IMAGE_INPUT_TOKENS
_CACHE_WRITE_MULTIPLE = CACHE_WRITE_MULTIPLE
_CACHE_READ_MULTIPLE = 0.10


@dataclass(frozen=True)
class ModelRates:
    """USD per million tokens."""

    input: float
    output: float


# Opus-class list rates, held deliberately at the high end: a cap priced from
# rates that are too low would be exceeded, one priced a little high only stops
# a run early. A model not listed is priced at the same ceiling.
_OPUS_CEILING = ModelRates(input=15.00, output=75.00)
RATES_BY_MODEL: dict[str, ModelRates] = {"claude-opus-4-8": _OPUS_CEILING}


# What the same tokens cost at the published list price. For information only:
# the cap is enforced on the ceiling figure above and never reads this table,
# so a stale list rate can misstate a report line but cannot loosen the cap.
LIST_RATES_BY_MODEL: dict[str, ModelRates] = {
    "claude-opus-4-8": ModelRates(input=5.00, output=25.00),
}


def rates_for(model: str) -> ModelRates:
    return RATES_BY_MODEL.get(model, _OPUS_CEILING)


def _list_ratio(model: str) -> float | None:
    """List price as a fraction of the ceiling price; None for an unlisted model."""
    listed = LIST_RATES_BY_MODEL.get(model)
    if listed is None:
        return None
    return listed.output / rates_for(model).output


def worst_case_call_usd(model: str) -> float:
    """The most one vision call can cost: full output, all input at cache-write."""
    r = rates_for(model)
    return (
        _WORST_CASE_INPUT_TOKENS * r.input * _CACHE_WRITE_MULTIPLE
        + _MAX_OUTPUT_TOKENS * r.output
    ) / _M


def _tokens(usage: Mapping[str, object], key: str) -> int:
    value = usage.get(key, 0)
    return value if isinstance(value, int) and value > 0 else 0


def usage_cost_usd(model: str, usage: Mapping[str, object] | None) -> float | None:
    """Real cost of one response from its reported usage; None when absent."""
    return _usage_cost(rates_for(model), usage)


def list_usage_cost_usd(model: str, usage: Mapping[str, object] | None) -> float | None:
    """The same usage at list rates; None when absent or the model has no list rate."""
    listed = LIST_RATES_BY_MODEL.get(model)
    return None if listed is None else _usage_cost(listed, usage)


def _usage_cost(r: ModelRates, usage: Mapping[str, object] | None) -> float | None:
    if not usage:
        return None
    plain = _tokens(usage, "input_tokens")
    write = _tokens(usage, "cache_creation_input_tokens")
    read = _tokens(usage, "cache_read_input_tokens")
    out = _tokens(usage, "output_tokens")
    if not (plain or write or read or out):
        return None  # an all-zero report is a missing one, never a free call
    return (
        plain * r.input
        + write * r.input * _CACHE_WRITE_MULTIPLE
        + read * r.input * _CACHE_READ_MULTIPLE
        + out * r.output
    ) / _M


@dataclass
class SpendBudget:
    """Spend against a hard cap: reserve before a call, settle after it."""

    cap_usd: float
    model: str
    reservation_usd: float = 0.02
    worst_case_usd: float | None = None
    spent_usd: float = 0.0
    spent_list_usd: float = 0.0  # the same spend at list rates; reporting only
    max_call_usd: float = 0.0

    def _worst(self) -> float:
        """The modeled worst case, or the dearest call seen if that was higher.

        The modeled ceiling rests on billing assumptions (image downscale,
        prompt size). A call that costs more than it has proved the model
        wrong, so no later call is allowed to start on the lower figure.
        """
        modeled = self.worst_case_usd
        if modeled is None:
            modeled = worst_case_call_usd(self.model)
        return max(modeled, self.max_call_usd)

    def can_start(self) -> bool:
        """True iff a worst-case call still fits under the cap."""
        return self.spent_usd + self._worst() <= self.cap_usd

    def reserve(self) -> None:
        """Charge the flat estimate before the call is made."""
        self.spent_usd += self.reservation_usd
        self.spent_list_usd += self.reservation_usd * (_list_ratio(self.model) or 0.0)

    def settle(self, usage: Mapping[str, object] | None) -> None:
        """Replace the reservation with the response's real cost."""
        actual = usage_cost_usd(self.model, usage)
        cost = self._worst() if actual is None else actual
        self.max_call_usd = max(self.max_call_usd, cost)
        self.spent_usd += cost - self.reservation_usd
        ratio = _list_ratio(self.model)
        if ratio is not None:
            listed = list_usage_cost_usd(self.model, usage)
            list_cost = cost * ratio if listed is None else listed
            self.spent_list_usd += list_cost - self.reservation_usd * ratio

    @property
    def list_priced(self) -> bool:
        """Whether ``spent_list_usd`` means anything (the model has a list rate)."""
        return _list_ratio(self.model) is not None
