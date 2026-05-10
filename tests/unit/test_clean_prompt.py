"""Unit tests for the cleanup-stage prompt + provenance hash helpers."""

from __future__ import annotations

import hashlib

from pursue_index.clean import prompt as clean_prompt


def test_system_prompt_is_a_stable_string() -> None:
    """System prompt must be a non-empty string with the must-do/must-not contract."""
    text = clean_prompt.system_prompt()
    assert isinstance(text, str)
    assert len(text) > 100
    # Contractual phrases the prompt MUST contain — they're the reason this
    # cleanup pass is safe to ship. If a future refactor drops them, the
    # test breaks loudly rather than silently letting the model paraphrase.
    assert "hyphenation" in text.lower()
    assert "[REDACTED]" in text
    assert "Return ONLY" in text or "Return only" in text


def test_prompt_sha256_is_stable_and_hex() -> None:
    """Same prompt twice → same sha; output is 64-char hex."""
    a = clean_prompt.prompt_sha256()
    b = clean_prompt.prompt_sha256()
    assert a == b
    assert len(a) == 64
    int(a, 16)  # parses as hex


def test_prompt_sha256_matches_explicit_hash() -> None:
    """Hash matches sha256 over the literal prompt bytes (UTF-8)."""
    expected = hashlib.sha256(
        clean_prompt.system_prompt().encode("utf-8")
    ).hexdigest()
    assert clean_prompt.prompt_sha256() == expected


def test_input_sha256_keys_on_text_only() -> None:
    """input_sha256 keys on the raw OCR text alone (not on model id, etc).

    Lets us identify *the same input* across runs even if we re-clean with a
    different model. The full idempotency key (text + model + prompt) is
    composed by ``idempotency_key``.
    """
    sha = clean_prompt.input_sha256("hello world\n")
    assert sha == hashlib.sha256(b"hello world\n").hexdigest()


def test_idempotency_key_changes_when_any_input_changes() -> None:
    """text, model_id, and prompt_sha all participate in the idempotency key."""
    base = clean_prompt.idempotency_key(
        text="raw page", model_id="claude-haiku-4-5", prompt_sha="abc"
    )
    different_text = clean_prompt.idempotency_key(
        text="other page", model_id="claude-haiku-4-5", prompt_sha="abc"
    )
    different_model = clean_prompt.idempotency_key(
        text="raw page", model_id="claude-sonnet-4-6", prompt_sha="abc"
    )
    different_prompt = clean_prompt.idempotency_key(
        text="raw page", model_id="claude-haiku-4-5", prompt_sha="def"
    )
    assert base != different_text
    assert base != different_model
    assert base != different_prompt
