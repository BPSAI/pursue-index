"""Typed verdict shapes + aggregate computation for the clean-quality
LLM-judge layer.

A judge row carries 8 per-check verdicts plus an aggregate roll-up.
Verdict values: ``pass | soft_fail | hard_fail | not_applicable | uncertain``.
Severity values: ``none | low | medium | high | critical``.

Aggregate semantics (per the plan):
- Any check returning ``hard_fail`` ⇒ aggregate verdict ``hard_fail``.
- ``voice_match`` with ``severity == "critical"`` ⇒ aggregate
  ``hard_fail`` (the journalist-misled threshold).
- Otherwise count ``soft_fail`` checks; verdict ``soft_fail`` if any.
- All ``not_applicable`` ⇒ aggregate ``not_applicable``.
- Else ``pass``.
"""

from __future__ import annotations

from typing import Any

# Names of the 8 checks the judge prompt evaluates. The interpretive_cleanups
# check carries a count rather than a verdict (it's purely descriptive); the
# other 7 carry verdict + severity.
CHECK_NAMES = (
    "hallucinated_facts",
    "fabricated_redactions",
    "length_ratio",
    "voice_match",
    "page_boundary_fidelity",
    "ocr_artifact_handling",
    "verbatim_quotability",
    "interpretive_cleanups",
)

VERDICT_VALUES = ("pass", "soft_fail", "hard_fail", "not_applicable", "uncertain")
SEVERITY_VALUES = ("none", "low", "medium", "high", "critical")


def _tally_check(
    name: str, body: dict[str, Any]
) -> tuple[int, int, int, int]:
    """Return (hard_fail, soft_fail, not_applicable, pass_or_actionable)
    deltas contributed by one check. Extracted from aggregate_checks
    to keep that function under the 50-line cap."""
    if name == "interpretive_cleanups":
        return 0, 0, 0, 0  # descriptive; doesn't contribute
    verdict = body.get("verdict", "pass")
    severity = body.get("severity", "none")
    # voice_match severity=critical is a hard-fail by special rule.
    if name == "voice_match" and severity == "critical":
        return 1, 0, 0, 1
    if verdict == "hard_fail":
        return 1, 0, 0, 1
    if verdict == "soft_fail":
        return 0, 1, 0, 1
    if verdict == "not_applicable":
        return 0, 0, 1, 0
    if verdict == "pass":
        return 0, 0, 0, 1
    return 0, 0, 0, 0  # uncertain — flagged for human review separately


def aggregate_checks(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compute the aggregate verdict block from per-check verdicts.

    Returns ``{verdict, hard_fail_count, soft_fail_count}`` with the
    semantics documented in the module docstring.
    """
    hard_fail_count = soft_fail_count = not_applicable_count = actionable = 0
    for name, body in checks.items():
        h, s, n, a = _tally_check(name, body)
        hard_fail_count += h
        soft_fail_count += s
        not_applicable_count += n
        actionable += a

    if hard_fail_count > 0:
        verdict = "hard_fail"
    elif soft_fail_count > 0:
        verdict = "soft_fail"
    elif actionable == 0 and not_applicable_count > 0:
        verdict = "not_applicable"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "hard_fail_count": hard_fail_count,
        "soft_fail_count": soft_fail_count,
    }
