"""Per-page review-priority scoring.

Composes available signals — OCR confidence, raw/cleaned length
divergence, gibberish density, optional judge verdict — into a 0-1
``review_priority`` score. Higher = more likely to need operator
review. Drives the top-K queue for /review.

Signals (weights tuned to match the original review-correct plan's
detection-signal list):

  signal                       weight if triggered    notes
  ───────────────────────────  ─────────────────────  ────────────────────────
  judge hard_fail               1.0 (max — clamps)    ship-blocker; no other signal can outvote
  judge soft_fail               +0.35                 flag for human review
  OCR confidence < 0.85         +0.30 scaled          linear from 0.5→0.85
  length divergence outside     +0.30                 ratio < 0.5 or > 2.0
    [0.5, 2.0]
  gibberish density > 0.20      +0.20 scaled          fraction of non-alpha-num
  raw text empty + cleaned      +0.40                 OCR failure indicator
    also empty + conf=0
"""

from __future__ import annotations

import re

_ALNUM_RE = re.compile(r"[A-Za-z0-9\s\.,;:'\"!?\-–—()\[\]/]")

_LENGTH_RATIO_MIN = 0.5
_LENGTH_RATIO_MAX = 2.0
_CONF_FLOOR = 0.5
_CONF_GOOD = 0.85
_GIBBERISH_THRESHOLD = 0.20


def _length_divergence_bump(raw: str, cleaned: str) -> float:
    if not raw:
        return 0.0
    ratio = len(cleaned) / max(len(raw), 1)
    if ratio < _LENGTH_RATIO_MIN or ratio > _LENGTH_RATIO_MAX:
        # Extreme divergence (>5x or <0.2x) bumps further — strong
        # signal of a refusal / preamble leak / cleanup blowup.
        if ratio < 0.2 or ratio > 5.0:
            return 0.50
        return 0.30
    return 0.0


def _gibberish_density(text: str) -> float:
    """Fraction of characters that aren't readable alpha-num-punctuation."""
    if not text:
        return 0.0
    readable = len(_ALNUM_RE.findall(text))
    return 1.0 - (readable / max(len(text), 1))


def _confidence_bump(ocr_confidence: float) -> float:
    """Confidence < 0.85 produces linear penalty up to 0.40."""
    if ocr_confidence >= _CONF_GOOD:
        return 0.0
    if ocr_confidence <= _CONF_FLOOR:
        return 0.40
    # linear scale between floor and good
    span = _CONF_GOOD - _CONF_FLOOR
    deficit = _CONF_GOOD - ocr_confidence
    return 0.40 * (deficit / span)


def _gibberish_bump(raw_text: str) -> float:
    density = _gibberish_density(raw_text)
    if density <= _GIBBERISH_THRESHOLD:
        return 0.0
    # linear scale: 0.20 at threshold → 0.20 bump, 1.0 → 0.20 max bump
    return 0.20 * min((density - _GIBBERISH_THRESHOLD) / 0.30, 1.0) * 1.5


def _empty_page_bump(raw_text: str, cleaned_text: str, ocr_confidence: float) -> float:
    if raw_text == "" and cleaned_text == "" and ocr_confidence == 0:
        return 0.40
    return 0.0


def score_page(
    *,
    raw_text: str,
    cleaned_text: str,
    ocr_confidence: float,
    qc_verdict: str | None,
) -> float:
    """Compute review_priority ∈ [0, 1] for one page.

    qc_verdict of ``hard_fail`` short-circuits to 1.0. Other signals
    accumulate; result clamped to 1.0.
    """
    if qc_verdict == "hard_fail":
        return 1.0
    score = 0.0
    if qc_verdict == "soft_fail":
        score += 0.35
    elif qc_verdict == "uncertain":
        score += 0.30
    score += _confidence_bump(ocr_confidence)
    score += _length_divergence_bump(raw_text, cleaned_text)
    score += _gibberish_bump(raw_text)
    score += _empty_page_bump(raw_text, cleaned_text, ocr_confidence)
    return min(score, 1.0)
