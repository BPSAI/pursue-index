"""Tests for `scripts/repair_altered_ocr_envelopes.py`.

The Anthropic vision OCR sometimes returns its
output inside a JSON envelope (``{"text": "...", "confidence": 99}``)
that fails to parse because inner double-quotes aren't escaped.
`_parse_response` in the canonical OCR module falls back to
``return raw`` on parse failure — which stuffs the envelope string
into the ``text`` field. This script extracts the inner text after
the fact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import repair_altered_ocr_envelopes as repair  # noqa: E402


def test_looks_like_envelope_matches_canonical_pattern() -> None:
    """The canonical pattern observed in committed data: `{\n  "text":
    "<content>", "confidence": 99 }`."""
    assert repair.looks_like_envelope(
        '{\n  "text": ""Orbs Launching Orbs"\\n\\n• Location: ..."\n}'
    )


def test_looks_like_envelope_matches_markdown_fenced() -> None:
    """Some calls return the envelope inside ```json fences."""
    raw = '```json\n{"text": "x", "confidence": 99}\n```'
    assert repair.looks_like_envelope(raw)


def test_looks_like_envelope_rejects_normal_text() -> None:
    assert not repair.looks_like_envelope("Just plain OCR text without an envelope.")
    assert not repair.looks_like_envelope("")
    # A document that mentions a JSON object in prose shouldn't trip.
    assert not repair.looks_like_envelope(
        'The document discusses {"text"} fields in a database schema.'
    )


def test_extract_envelope_text_strips_wrapper_and_unescapes() -> None:
    raw = '{\n  "text": "Hello\\nWorld\\t\\"quoted\\"", "confidence": 99\n}'
    assert repair.extract_envelope_text(raw) == 'Hello\nWorld\t"quoted"'


def test_extract_envelope_text_handles_unescaped_inner_quotes() -> None:
    """The real-world case: model emits unescaped inner ``"`` inside
    the ``"text"`` field. json.loads chokes on it; our extractor
    works on string indices instead."""
    raw = (
        '{\n  "text": "\\"Orbs Launching Orbs\\"\\n\\n• Location: Western U.S."'
        ', "confidence": 99\n}'
    )
    inner = repair.extract_envelope_text(raw)
    assert inner is not None
    assert '"Orbs Launching Orbs"' in inner
    assert "Location: Western U.S." in inner


def test_extract_envelope_text_returns_none_when_not_an_envelope() -> None:
    assert repair.extract_envelope_text("Plain text, no envelope") is None


def test_repair_jsonl_rewrites_only_affected_rows(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    rows = [
        {"page": 1, "text": "Clean page 1 text", "confidence": 95},
        {
            "page": 2,
            "text": '{\n  "text": "Wrapped page 2 text", "confidence": 92\n}',
            "confidence": 0,
        },
        {"page": 3, "text": "Clean page 3 text", "confidence": 88},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    repaired, total = repair.repair_jsonl(path)
    assert repaired == 1
    assert total == 3
    new_rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert new_rows[0]["text"] == "Clean page 1 text"
    assert new_rows[1]["text"] == "Wrapped page 2 text"
    assert new_rows[2]["text"] == "Clean page 3 text"


def test_repair_jsonl_idempotent_on_already_clean(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    rows = [{"page": 1, "text": "Clean", "confidence": 90}]
    original = "\n".join(json.dumps(r) for r in rows) + "\n"
    path.write_text(original, encoding="utf-8")
    repaired, total = repair.repair_jsonl(path)
    assert repaired == 0
    assert total == 1
    # File unchanged (no rewrite when nothing to repair).
    assert path.read_text() == original


def test_repair_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "pages.jsonl"
    path.write_text(
        json.dumps({"page": 1, "text": "x"}) + "\n\n"
        + json.dumps({"page": 2, "text": "y"}) + "\n",
        encoding="utf-8",
    )
    repaired, total = repair.repair_jsonl(path)
    assert repaired == 0
    assert total == 2
