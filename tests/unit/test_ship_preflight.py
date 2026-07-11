"""Verify-before-spend OCR preflight for the turnkey ship-tranche path.

Encodes the operated methodology as a hard gate: refuse to spend on OCR unless
the engine is the operated Sonnet path (llm-dots / llm), concurrency is the
operated 8, and the Anthropic key resolves. This is the guard that makes the
Release-4 fumble (stale env → tesseract-primary, download-concurrency 4
mis-borrowed for OCR) impossible to repeat.
"""

from __future__ import annotations

from pursue_index.release.ship import estimate_cost_usd, preflight_ocr


def test_preflight_passes_operated_config():
    r = preflight_ocr(engine="llm-dots", concurrency=8, anthropic_key_present=True)
    assert r.ok is True
    assert r.errors == []


def test_preflight_accepts_plain_llm():
    # llm (Sonnet, no dots backstop) is acceptable; dots is only the 400 fallback.
    r = preflight_ocr(engine="llm", concurrency=8, anthropic_key_present=True)
    assert r.ok is True


def test_preflight_refuses_auto_and_tesseract():
    for bad in ("auto", "tesseract", "surya"):
        r = preflight_ocr(engine=bad, concurrency=8, anthropic_key_present=True)
        assert r.ok is False
        assert any("engine" in e.lower() for e in r.errors), bad


def test_preflight_refuses_low_concurrency():
    r = preflight_ocr(engine="llm-dots", concurrency=4, anthropic_key_present=True)
    assert r.ok is False
    assert any("concurrenc" in e.lower() for e in r.errors)


def test_preflight_refuses_missing_key():
    r = preflight_ocr(engine="llm-dots", concurrency=8, anthropic_key_present=False)
    assert r.ok is False
    assert any("key" in e.lower() for e in r.errors)


def test_preflight_refuses_unset_engine():
    r = preflight_ocr(engine=None, concurrency=8, anthropic_key_present=True)
    assert r.ok is False


def test_estimate_cost_scales_and_is_positive():
    assert estimate_cost_usd(pages=200) > estimate_cost_usd(pages=20) > 0.0
    # cards-only estimate (credential-free surface, no page counts yet) also works
    assert estimate_cost_usd(cards=14) > 0.0
