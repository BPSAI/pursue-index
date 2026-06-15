"""S7.1 OCR prompt-contract tests.

Pins the three operator-approved transcription-policy rules into the LLM OCR
system prompt (see opsec `findings/2026-06-15-s71-vlm-bakeoff.md` §5), plus the
load-bearing cache-correctness behavior: the image-content cache must key on the
prompt version, so a contract change actually busts the cache instead of
silently returning old-prompt transcriptions on re-OCR.

These assert on stable concept tokens, not exact phrasing, so reasonable prompt
wording edits don't break the contract — only dropping a rule does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from pursue_index.ocr import llm as ocr_llm

from .test_ocr_llm import _FakeAnthropic, _FakeUsage, _patch_client, _structured_response


# ---------------------------------------------------------------------------
# Cycle 1 — the prompt encodes the three S7.1 contract rules
# ---------------------------------------------------------------------------
def test_prompt_transcribes_exemption_codes_verbatim() -> None:
    """Printed FOIA exemption codes (e.g. (b)(1)1.4a) are transcribed VERBATIM
    inline — the printed code IS the redaction marker — not wrapped in a
    [REDACTED <code>] sentinel. Matches operator GT convention (S7.1 §5,
    revised 2026-06-15 after the behavioral check + operator decision)."""
    p = ocr_llm._SYSTEM_PROMPT.lower()
    assert "exemption" in p
    assert "(b)(1)" in ocr_llm._SYSTEM_PROMPT  # a concrete code example is shown
    assert "[redacted]" in p  # bare sentinel retained for code-less black bars
    assert "redaction marker" in p  # the printed code is the marker
    # we explicitly do NOT instruct the wrapper form
    assert "[redacted (b)" not in p


def test_prompt_has_declassification_strikethrough_rule() -> None:
    """A colored strike-through over a still-legible classification marking is a
    declassification annotation, not a redaction → transcribe it as content."""
    p = ocr_llm._SYSTEM_PROMPT.lower()
    assert "declassif" in p
    assert "strike" in p  # strike-through / struck
    # the rule explicitly says such markings are NOT redactions
    assert "not a redaction" in p or "not [redacted]" in p


def test_prompt_has_strict_no_fill_illegible_rule() -> None:
    """Covered/unreadable text is `[ILLEGIBLE]`; never fill from outside
    knowledge or repeated boilerplate (provenance bright line)."""
    p = ocr_llm._SYSTEM_PROMPT.lower()
    assert "[illegible]" in p
    assert "physically visible" in p or "actually visible" in p
    assert "outside knowledge" in p or "do not fill" in p or "from memory" in p


# ---------------------------------------------------------------------------
# Cycle 2 — the image cache keys on the prompt version (bust on contract change)
# ---------------------------------------------------------------------------
def test_prompt_change_busts_image_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same image + different system prompt ⇒ cache MISS (new API call).

    The cache previously keyed on image bytes only, so a prompt-contract change
    would be silently defeated — re-OCR returned the old-prompt transcription.
    """
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([
        (_structured_response("old-prompt text", 90), _FakeUsage(1000, 50)),
        (_structured_response("new-prompt text", 88), _FakeUsage(1000, 50)),
    ])
    _patch_client(monkeypatch, client)

    img = Image.new("RGB", (24, 24), color=(11, 22, 33))

    text1, _ = ocr_llm.ocr_image(img)
    assert text1 == "old-prompt text"
    assert len(client.messages.calls) == 1

    # Change the contract; the identical image must NOT hit the stale cache.
    monkeypatch.setattr(
        ocr_llm, "_SYSTEM_PROMPT", ocr_llm._SYSTEM_PROMPT + "\n- A NEW CONTRACT RULE."
    )
    text2, _ = ocr_llm.ocr_image(img)
    assert text2 == "new-prompt text"
    assert len(client.messages.calls) == 2, "prompt change must bust the image cache"


def test_same_prompt_still_hits_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cache busting on prompt change must not break same-prompt cache hits."""
    monkeypatch.setattr(ocr_llm, "_cache_dir", lambda: tmp_path / "cache")
    client = _FakeAnthropic([(_structured_response("cached", 91), _FakeUsage(1000, 50))])
    _patch_client(monkeypatch, client)

    img = Image.new("RGB", (24, 24), color=(7, 7, 7))
    ocr_llm.ocr_image(img)
    ocr_llm.ocr_image(img)  # identical prompt + image → must be cached
    assert len(client.messages.calls) == 1
