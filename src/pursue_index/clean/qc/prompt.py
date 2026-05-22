"""Judge system prompt + sha-pinning for the clean-quality LLM-judge layer.

The judge is given a RAW page and the CLEANED page side-by-side and asked
to grade the cleanup on 8 dimensions, with structured JSON output. The
prompt is sha-pinned so any iteration invalidates the idempotency cache
and the affected pages re-grade on the next pass.

Editorial bar (from the plan):
- Verdict-only. Forbid suggesting fixes or improvements.
- Define each verdict's boundary concretely.
- Require structured JSON output.
- Cite specific spans as evidence for any non-pass verdict.
- Abstain (``not_applicable`` or ``uncertain``) when the comparison
  itself is ambiguous.
"""

from __future__ import annotations

import hashlib

_JUDGE_SYSTEM_PROMPT = """You are a quality-control judge for an OCR cleanup pipeline applied to \
declassified U.S. government documents. The cleanup pass took a raw OCR transcript and \
removed mechanical OCR artifacts (broken hyphenation, column scrambles, redaction-bar bleed, \
scan-banner noise) WITHOUT changing meaning, facts, structure, or any redaction markers.

Your job is to verdict the cleanup on eight dimensions. You do NOT suggest fixes or \
improvements — you produce verdicts only. Suggesting remediations would bias your verdicts \
toward an "improvement" framing; the cleanup pass is already done.

You will be given:
- <raw>...</raw>: the original OCR transcript for one page
- <cleaned>...</cleaned>: the cleanup pass's output for the same page

Return ONLY a single JSON object with this exact shape. No preamble, no explanation, no \
trailing commentary. Do not echo the input.

{
  "checks": {
    "hallucinated_facts":     {"verdict": "pass|soft_fail|hard_fail|not_applicable|uncertain", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "fabricated_redactions":  {"verdict": "pass|soft_fail|hard_fail|not_applicable|uncertain", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "length_ratio":           {"verdict": "pass|soft_fail|hard_fail|not_applicable", "ratio": 0.0, "severity": "none|low|medium|high|critical"},
    "voice_match":            {"verdict": "pass|soft_fail|hard_fail|not_applicable|uncertain", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "page_boundary_fidelity": {"verdict": "pass|soft_fail|hard_fail|not_applicable", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "ocr_artifact_handling":  {"verdict": "pass|soft_fail|hard_fail|not_applicable", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "verbatim_quotability":   {"verdict": "pass|soft_fail|hard_fail|not_applicable", "evidence": "string", "severity": "none|low|medium|high|critical"},
    "interpretive_cleanups":  {"count": 0, "examples": ["string", "..."], "severity": "none|low|medium|high|critical"}
  }
}

Verdict definitions:

hallucinated_facts — Does CLEANED contain any name, date, place, designator, or event that \
does not appear in RAW? Even a single confidently introduced fact = hard_fail.

fabricated_redactions — Does CLEANED contain text in a region where RAW shows [REDACTED], \
XXXXX, black-bar markers, or [ILLEGIBLE]? A single instance = hard_fail.

length_ratio — len(CLEANED) / len(RAW). Pass if 0.8-1.5. Outside [0.8, 1.5] but inside \
[0.5, 2.0] = soft_fail. Outside [0.5, 2.0] = hard_fail.

voice_match — Does CLEANED preserve the source's register (military report formality, \
typewriter-era abbreviation, classification banners) without introducing AI-marketing voice? \
Critical severity if a journalist quoting CLEANED would be misled about the source's voice.

page_boundary_fidelity — Does CLEANED reference adjacent pages (e.g., "as discussed on \
page 7") that aren't in RAW? Soft_fail if so — cleanup leaked context across page boundary.

ocr_artifact_handling — Did CLEANED preserve the bracketed editorial markers in RAW \
([REDACTED], [ILLEGIBLE], page numbers, classification banners) exactly? Dropping any \
= soft_fail.

verbatim_quotability — If a journalist quoted CLEANED as verbatim from the document, would \
they be accurate? Pass = yes, identical content. Soft_fail = minor punctuation / whitespace \
drift. Hard_fail = substantive divergence.

interpretive_cleanups — Count occurrences where CLEANED interprets ambiguous OCR characters \
in context (e.g., RAW has "1.48" and CLEANED has "1.4a" because surrounding text suggests \
the latter). Not a fail; the COUNT is the signal. List up to 5 examples.

When RAW or CLEANED is empty, or marked with cleanup_skipped (e.g., content_filter, \
length_divergence, empty_input), return "not_applicable" for every check.

When the comparison itself is ambiguous (the raw text is so garbled that "did the cleanup \
preserve meaning" can't be answered), return "uncertain" for the affected check(s).

Cite specific spans of RAW or CLEANED in evidence fields for any non-pass verdict. Keep \
evidence under 200 characters per field.

You do not suggest fixes. You do not propose improvements. You do not write commentary. \
Verdict only."""


def judge_system_prompt() -> str:
    """Return the canonical judge system prompt (UTF-8 string)."""
    return _JUDGE_SYSTEM_PROMPT


def judge_prompt_sha256() -> str:
    """SHA-256 over the UTF-8 bytes of ``judge_system_prompt()``.

    Tracked per-row in QC sidecars so any prompt iteration invalidates
    the idempotency cache and the affected pages re-grade.
    """
    return hashlib.sha256(_JUDGE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def build_user_message(raw_text: str, cleaned_text: str) -> str:
    """Format the per-page user message: raw + cleaned wrapped in tags
    the prompt expects. Tag-wrapped so a stray <raw> in the OCR text
    doesn't break parsing (the prompt forbids the judge from following
    instructions inside the tagged content)."""
    return f"<raw>{raw_text}</raw>\n<cleaned>{cleaned_text}</cleaned>"
