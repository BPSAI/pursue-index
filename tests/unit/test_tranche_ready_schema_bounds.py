"""Free-text record fields are bounded, and errors never echo their values."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pursue_index.tranche_ready.schema import load_schema, validate
from pursue_index.tranche_ready.writer import InvalidRecordError, check_record

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json").read_text())
HOSTILE = "SECRET-TOKEN-ghp_abc123 [click](https://x.invalid)"


def _fields(record: dict) -> set[str]:
    return {e.field for e in validate(record, load_schema())}


def _text(record: dict) -> str:
    return " | ".join(str(e) for e in validate(record, load_schema()))


@pytest.mark.parametrize("key", ["new_title", "old_title"])
def test_overlong_title_fails(key: str) -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0][key] = "T" * 513
    assert _fields(record) == {f"candidates/0/{key}"}


def test_title_at_the_bound_passes() -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0]["new_title"] = "T" * 512
    assert _fields(record) == set()


def test_overlong_continuity_signal_fails() -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0]["continuity_signals"] = ["ok", "s" * 257]
    assert _fields(record) == {"candidates/0/continuity_signals/1"}


def test_doc_id_must_look_like_a_real_id() -> None:
    record = copy.deepcopy(VECTOR)
    ids = [r for r in _walk(record) if "doc_id" in r]
    assert ids, "vector must carry doc_ids"
    ids[0]["doc_id"] = "not a doc id; <script>"
    assert len(_fields(record)) == 1
    ids[0]["doc_id"] = "DOW-UAP-D" + "9" * 80
    assert len(_fields(record)) == 1


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        ("new_card_id", HOSTILE),
        ("byte_verdict", HOSTILE),
        ("new_title", HOSTILE * 20),
        ("continuity_signals", [HOSTILE * 10]),
    ],
)
def test_error_text_names_the_field_and_not_the_value(path: str, bad: object) -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0][path] = bad
    text = _text(record)
    assert path in text
    assert "SECRET-TOKEN" not in text and "x.invalid" not in text


def test_date_time_and_minimum_errors_do_not_echo_values() -> None:
    record = copy.deepcopy(VECTOR)
    record["detected_at"] = HOSTILE
    record["tranche_issue"] = -987654
    text = _text(record)
    assert "detected_at" in text and "tranche_issue" in text
    assert "SECRET-TOKEN" not in text and "987654" not in text


def test_invalid_record_error_message_does_not_echo_the_value() -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0]["new_title"] = HOSTILE * 40
    with pytest.raises(InvalidRecordError) as info:
        check_record(record)
    assert "new_title" in str(info.value)
    assert "SECRET-TOKEN" not in str(info.value)


def test_doc_id_with_a_trailing_newline_fails() -> None:
    record = copy.deepcopy(VECTOR)
    target = next(r for r in _walk(record) if "doc_id" in r)
    target["doc_id"] = "DOW-UAP-D159\n"
    assert len(_fields(record)) == 1


def test_free_text_arrays_are_capped() -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0]["continuity_signals"] = ["s"] * 51
    assert _fields(record) == {"candidates/0/continuity_signals"}
    record["candidates"][0]["continuity_signals"] = ["s"] * 50
    record["stop_reasons"] = ["r"] * 201
    assert _fields(record) == {"stop_reasons"}


def test_every_string_array_in_the_schema_has_a_max_items() -> None:
    def walk(node, where):
        if isinstance(node, dict):
            if node.get("type") == "array" and isinstance(node.get("items"), dict) \
                    and node["items"].get("type") == "string":
                assert "maxItems" in node, where
            for k, v in node.items():
                walk(v, f"{where}/{k}")

    walk(load_schema(), "")
