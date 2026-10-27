"""The ship-tranche runbook resolves its tranche safely and stays generic."""

from __future__ import annotations

import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "ship-tranche.md"


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def test_issue_query_filters_on_label_and_poll_bot_author() -> None:
    text = _text()
    assert "--label tranche-detected" in text
    assert "--author" in text and "github-actions" in text
    assert '--search "tranche detected"' not in text


def test_sha_is_validated_as_64_hex_and_stops_on_mismatch() -> None:
    text = _text()
    pattern = "^[0-9a-f]{64}$"
    assert pattern in text
    start = text.index(pattern)
    assert re.search(r"STOP", text[start : start + 600])


def test_frontmatter_does_not_grant_unrestricted_bash() -> None:
    assert "Bash(*)" not in _text()


def test_sha_expansions_are_quoted() -> None:
    for line in _text().splitlines():
        for m in re.finditer(r"\$\{?SHA\b", line):
            before = line[: m.start()]
            assert before.count('"') % 2 == 1, f"unquoted SHA expansion: {line.strip()}"


def test_env_is_sourced_only_after_the_approval_gate() -> None:
    text = _text()
    pre = text.split("## Workflow")[0]
    assert "; source " not in pre
    gate = text.index("HUMAN GATE #1")
    assert text.index("; source ") > gate


def test_runbook_does_not_name_private_sibling_material() -> None:
    text = _text()
    for needle in ("pursue-opsec-staging", "same-account", "findings/", "state.md"):
        assert needle not in text, needle
    assert "private ops runbook" in text
