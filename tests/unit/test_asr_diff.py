"""Word-level alignment of two ASR engines' transcripts of the same audio
(``pursue_index.transcribe.asr_diff``).

A second engine catches *mishearings* -- a word one engine misheard that
the other got right. It cannot catch a word both engines misheard the same
way, or an error already in the source audio: that limit is asserted
on the methodology page (see ``methodology-asr-diff.test.ts``), not here.
"""

from __future__ import annotations

from pursue_index.transcribe.asr_diff import (
    AGREEMENT_THRESHOLD,
    align_transcripts,
    classify_agreement,
)


def test_identical_transcripts_agree_completely() -> None:
    text = "the quick brown fox jumps over the lazy dog"
    result = align_transcripts(text, text)
    assert result.agreement == 1.0
    assert result.disagreeing_spans == []
    assert result.word_count_a == result.word_count_b == 9


def test_a_single_misheard_word_is_the_exact_disagreeing_span() -> None:
    text_a = "the pilot reported a bright light over the ridge"
    text_b = "the pilot reported a bright flight over the ridge"
    result = align_transcripts(text_a, text_b)
    assert 0.0 < result.agreement < 1.0
    assert len(result.disagreeing_spans) == 1
    span = result.disagreeing_spans[0]
    assert span.to_dict() == {
        "a_text": "light",
        "b_text": "flight",
        "a_range": [5, 6],
        "b_range": [5, 6],
    }


def test_case_and_surrounding_punctuation_alone_are_not_disagreements() -> None:
    text_a = "Yes, I saw it."
    text_b = "yes i saw it"
    result = align_transcripts(text_a, text_b)
    assert result.agreement == 1.0
    assert result.disagreeing_spans == []


def test_an_inserted_word_is_its_own_span_quoting_only_the_new_side() -> None:
    text_a = "it came from the north"
    text_b = "it definitely came from the north"
    result = align_transcripts(text_a, text_b)
    assert len(result.disagreeing_spans) == 1
    span = result.disagreeing_spans[0]
    assert span.a_text == ""
    assert span.b_text == "definitely"


def test_completely_different_transcripts_disagree_heavily() -> None:
    result = align_transcripts("alpha beta gamma", "delta epsilon zeta")
    assert result.agreement == 0.0
    assert len(result.disagreeing_spans) == 1


def test_classify_agreement_uses_the_committed_threshold_by_default() -> None:
    assert classify_agreement(AGREEMENT_THRESHOLD) == "judged"
    assert classify_agreement(AGREEMENT_THRESHOLD - 0.01) == "review"


def test_classify_agreement_accepts_an_explicit_threshold() -> None:
    assert classify_agreement(0.5, threshold=0.4) == "judged"
    assert classify_agreement(0.5, threshold=0.6) == "review"
