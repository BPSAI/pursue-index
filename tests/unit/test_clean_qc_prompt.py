"""Tests for ``pursue_index.clean.qc.prompt``.

Pins the judge system prompt's structural contract + the sha256
hashing used as the cache-invalidation signal.
"""

from __future__ import annotations

import hashlib

from pursue_index.clean.qc import prompt


def test_judge_system_prompt_is_non_empty_utf8() -> None:
    p = prompt.judge_system_prompt()
    assert isinstance(p, str)
    assert len(p) > 200, "judge prompt should be substantial"
    p.encode("utf-8")  # smoke-test no encoding errors


def test_judge_system_prompt_includes_eight_check_names() -> None:
    """The prompt is the load-bearing schema definition for the judge;
    if any check name moves the judge will silently omit it."""
    from pursue_index.clean.qc import schema
    p = prompt.judge_system_prompt()
    for name in schema.CHECK_NAMES:
        assert name in p, f"prompt missing check: {name}"


def test_judge_system_prompt_forbids_remediation_suggestions() -> None:
    """Per plan editorial bar — judge does verdicts only, no fixes."""
    p = prompt.judge_system_prompt().lower()
    # The prompt must explicitly forbid suggesting fixes / improvements
    # — otherwise judges drift toward the "this could be better" frame.
    assert "do not suggest" in p or "no suggestions" in p or "verdict only" in p


def test_judge_prompt_sha256_is_stable() -> None:
    """sha is deterministic — same prompt → same sha across runs."""
    s1 = prompt.judge_prompt_sha256()
    s2 = prompt.judge_prompt_sha256()
    assert s1 == s2
    assert len(s1) == 64  # sha256 hex
    # Recompute from bytes — should match (idiomatic check)
    expected = hashlib.sha256(prompt.judge_system_prompt().encode("utf-8")).hexdigest()
    assert s1 == expected
