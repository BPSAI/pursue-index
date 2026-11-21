"""Prices, token estimates and the spend-cap pre-flight for the bake-off harness."""

from __future__ import annotations

from collections.abc import Mapping

# (input, output) dollars per million tokens.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0)}
DEFAULT_HARD_CAP_USD = 8.0
# Opus 5.5 always thinks, and thinking tokens count against max_tokens, so it
# gets a larger ceiling than the client's default 2048. 8000 at medium effort
# keeps its worst case under the default cap; a max_tokens stop is recorded.
THINKING_MODEL = "claude-opus-5-5"
_THINKING_MAX_TOKENS = 8000
_DEFAULT_MAX_TOKENS = 2048
THINKING_EFFORT = "medium"
IMAGE_TOKENS = 4784  # per image at the client's 1,568px cap
PROMPT_TOKENS = 230 + 20  # system prompt + the user text
EXPECTED_OUTPUT_TOKENS = 700
EXPECTED_THINKING_TOKENS = 1500


def max_tokens_for(model: str) -> int:
    return _THINKING_MAX_TOKENS if model == THINKING_MODEL else _DEFAULT_MAX_TOKENS


def parse_prices(specs: list[str]) -> dict[str, tuple[float, float]]:
    """Built-in prices overlaid with ``MODEL=IN/OUT`` specs (dollars per MTok)."""
    prices = dict(DEFAULT_PRICES)
    for spec in specs:
        model, sep, rates = spec.partition("=")
        r_in, slash, r_out = rates.partition("/")
        try:
            pair = (float(r_in), float(r_out))
        except ValueError:
            pair = (-1.0, -1.0)
        if not (model and sep and slash) or min(pair) < 0:
            raise ValueError(f"bad --price {spec!r}; expected MODEL=IN/OUT, e.g. claude-x=5/25")
        prices[model] = pair
    return prices


def _usd(prices: Mapping[str, tuple[float, float]], model: str,
         input_tokens: int, output_tokens: int) -> float:
    r_in, r_out = prices[model]
    return (input_tokens * r_in + output_tokens * r_out) / 1e6


def worst_case_call_usd(model: str, prices: Mapping[str, tuple[float, float]]) -> float:
    return _usd(prices, model, IMAGE_TOKENS + PROMPT_TOKENS, max_tokens_for(model))


def call_cost_usd(model: str, usage: Mapping[str, int] | None,
                  prices: Mapping[str, tuple[float, float]]) -> float:
    """Metered cost of one response; a response with no usage costs its worst case."""
    if not usage or not any(usage.get(k) for k in ("input_tokens", "output_tokens")):
        return worst_case_call_usd(model, prices)
    r_in, _ = prices[model]
    cache = (usage.get("cache_creation_input_tokens", 0) * 1.25
             + usage.get("cache_read_input_tokens", 0) * 0.10) * r_in / 1e6
    return _usd(prices, model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)) + cache


def expected_output_tokens(model: str) -> int:
    return EXPECTED_OUTPUT_TOKENS + (EXPECTED_THINKING_TOKENS if model == THINKING_MODEL else 0)


def estimate(n_pages: int, models: tuple[str, ...],
             prices: Mapping[str, tuple[float, float]]) -> dict[str, dict[str, float | None]]:
    """Per-arm expected and worst-case totals; an arm with no price has ``None`` dollars."""
    rows: dict[str, dict[str, float | None]] = {}
    in_tok = IMAGE_TOKENS + PROMPT_TOKENS
    for m in models:
        out_tok = expected_output_tokens(m)
        priced = m in prices
        per_page = _usd(prices, m, in_tok, out_tok) if priced else None
        rows[m] = {"input_tokens": in_tok, "output_tokens": out_tok, "per_page_usd": per_page,
                   "total_usd": None if per_page is None else n_pages * per_page,
                   "worst_case_total_usd": n_pages * worst_case_call_usd(m, prices) if priced else None}
    return rows


def preflight(est: Mapping[str, Mapping[str, float | None]], cap: float) -> list[str]:
    """Reasons a run must not start; empty means it may.

    Refuses when the arms' summed expected spend exceeds the cap, or any single
    arm's worst case does, or an arm has no price.
    """
    reasons = [f"{m}: no price (pass --price {m}=IN/OUT)" for m, r in est.items()
               if r["total_usd"] is None]
    priced = {m: r for m, r in est.items() if r["total_usd"] is not None}
    total = sum(r["total_usd"] or 0.0 for r in priced.values())
    if total > cap:
        names = ", ".join(priced)
        reasons.append(f"summed expected ${total:.2f} across arms ({names}) exceeds the ${cap:.2f} cap")
    for m, r in priced.items():
        worst = r["worst_case_total_usd"] or 0.0
        if worst > cap:
            reasons.append(f"{m}: worst case ${worst:.2f} exceeds the ${cap:.2f} cap "
                           f"(max_tokens {max_tokens_for(m)})")
    return reasons
