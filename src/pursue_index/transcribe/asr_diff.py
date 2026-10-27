"""Word-level diff between two ASR engines' transcripts of the same audio.

Two independent engines reading the same audio occasionally disagree on a
word -- a homophone, a mumbled syllable, crosstalk. Aligning their output at
the word level and reporting the exact spans where they diverge turns "this
transcript is unverified" into "here are the N words a human should listen
to." ``AGREEMENT_THRESHOLD`` is the committed cutoff:
at/above it the transcript is accepted (``judged``), below it the
disagreeing spans go to human review (``review``).

This catches *mishearings* -- a word one engine got right and the other
didn't. It does NOT catch a word both engines mishear the same way, or an
error already present in the source audio; two engines agreeing is
necessary but not sufficient for correctness. See the methodology page for
the reader-facing statement of that limit.

Pure: no I/O, no network. Callers (``asr_diff_runner``) supply both engines'
text and write the sidecar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from difflib import SequenceMatcher

# First-cut cutoff, not yet calibrated against a real second engine's
# agreement distribution -- see the task that introduced this module.
AGREEMENT_THRESHOLD = 0.90


def _words(text: str) -> list[str]:
    return str(text or "").split()


def _normalized(word: str) -> str:
    return word.casefold().strip(".,?!;:\"'-")


@dataclass(frozen=True)
class DisagreeingSpan:
    """One stretch where the two engines' word sequences diverge.

    ``a_text``/``b_text`` quote the ORIGINAL (not normalized) words from
    each side, so a human reviewer sees exactly what each engine wrote. One
    side is empty for a pure insertion/deletion.
    """

    a_text: str
    b_text: str
    a_range: tuple[int, int]
    b_range: tuple[int, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "a_text": self.a_text,
            "b_text": self.b_text,
            "a_range": list(self.a_range),
            "b_range": list(self.b_range),
        }


@dataclass(frozen=True)
class AsrDiffResult:
    """The alignment outcome for one pair of transcripts."""

    agreement: float
    word_count_a: int
    word_count_b: int
    disagreeing_spans: list[DisagreeingSpan]

    def to_dict(self) -> dict[str, object]:
        return {
            "agreement": self.agreement,
            "word_count_a": self.word_count_a,
            "word_count_b": self.word_count_b,
            "disagreeing_spans": [s.to_dict() for s in self.disagreeing_spans],
        }


def align_transcripts(text_a: str, text_b: str) -> AsrDiffResult:
    """Align ``text_a`` and ``text_b`` at the word level.

    ``agreement`` is ``difflib.SequenceMatcher.ratio()`` over normalized
    words (case and surrounding punctuation ignored, so re-punctuation
    alone is never counted as a disagreement). Each non-``equal`` opcode
    becomes one :class:`DisagreeingSpan`.
    """
    words_a = _words(text_a)
    words_b = _words(text_b)
    norm_a = [_normalized(w) for w in words_a]
    norm_b = [_normalized(w) for w in words_b]
    matcher = SequenceMatcher(a=norm_a, b=norm_b, autojunk=False)
    spans = [
        DisagreeingSpan(
            a_text=" ".join(words_a[i1:i2]),
            b_text=" ".join(words_b[j1:j2]),
            a_range=(i1, i2),
            b_range=(j1, j2),
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
    return AsrDiffResult(
        agreement=matcher.ratio(),
        word_count_a=len(words_a),
        word_count_b=len(words_b),
        disagreeing_spans=spans,
    )


def classify_agreement(agreement: float, threshold: float = AGREEMENT_THRESHOLD) -> str:
    """``judged`` at/above ``threshold``, else ``review``."""
    return "judged" if agreement >= threshold else "review"


def derive_status(
    agreement: object, threshold: object, min_words: object,
) -> str:
    """Re-derive ``judged``/``review`` from raw evidence; fail closed.

    ``judged`` needs numeric agreement at/above numeric threshold AND at
    least one word on both sides -- two silent transcripts agree on nothing --
    and an agreement inside [0, 1]; a ratio outside it is not evidence.
    Anything missing or malformed is ``review``.
    """
    nums = (agreement, threshold, min_words)
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in nums):
        return "review"
    if min_words < 1 or not math.isfinite(agreement) or not 0.0 <= agreement <= 1.0:
        return "review"
    return classify_agreement(float(agreement), float(threshold))


def effective_threshold(published: object) -> object:
    """The cutoff a re-derivation may use: never below the committed one.

    A bundle or sidecar is data an editor can change, so the threshold it
    carries is only ever allowed to be STRICTER than ``AGREEMENT_THRESHOLD``.
    A non-numeric value is returned unchanged so ``derive_status`` fails closed.
    """
    if isinstance(published, bool) or not isinstance(published, (int, float)):
        return published
    return max(float(published), AGREEMENT_THRESHOLD)


def classify_result(result: AsrDiffResult, threshold: float = AGREEMENT_THRESHOLD) -> str:
    """Classify a full alignment result; zero words on either side is ``review``."""
    return derive_status(
        result.agreement, threshold, min(result.word_count_a, result.word_count_b),
    )
