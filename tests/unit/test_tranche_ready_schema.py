"""``pursue_index.tranche_ready.schema`` -- the dependency-free validator.

The poll lane installs only the hash-locked ``requirements-poll.txt`` set,
which carries no ``jsonschema``; the validator interprets the vendored
schema document itself (the subset of JSON Schema 2020-12 that document
uses) and names the failing field in every error, because that name is what
the poll's failure issue shows the operator. A keyword it does not
implement fails closed at load time, so a schema bump can never be
silently half-validated.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pursue_index.tranche_ready.schema import (
    UnsupportedSchemaError,
    load_schema,
    schema_path,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR = json.loads((REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json").read_text())


def _errors(record: dict) -> list[str]:
    return [str(e) for e in validate(record, load_schema())]


def test_schema_path_is_the_vendored_copy_in_the_installed_checkout() -> None:
    """Anchored to the code (like ``installed_scripts_dir``), never to the
    data root a CLI run stands in."""
    assert schema_path() == REPO_ROOT / "schemas" / "tranche-ready.schema.json"


def test_the_release_7_vector_validates() -> None:
    assert _errors(VECTOR) == []


def test_a_missing_required_field_is_named() -> None:
    record = copy.deepcopy(VECTOR)
    del record["fetch"]
    [error] = validate(record, load_schema())
    assert error.field == "fetch"
    assert "fetch" in str(error) and "required" in str(error)


def test_nested_pattern_enum_and_extra_property_errors_name_their_path() -> None:
    record = copy.deepcopy(VECTOR)
    record["candidates"][0]["new_card_id"] = "NOT-HEX"
    record["candidates"][0]["byte_verdict"] = "probably-fine"
    record["pages"]["surprise"] = 1
    fields = {e.field for e in validate(record, load_schema())}
    assert fields == {
        "candidates/0/new_card_id", "candidates/0/byte_verdict", "pages/surprise",
    }


def test_type_const_minimum_and_date_time_are_enforced() -> None:
    record = copy.deepcopy(VECTOR)
    record["schema_version"] = "2.0.0"
    record["tranche_issue"] = 0
    record["manifest"]["old_row_count"] = True  # a bool is not an integer
    record["detected_at"] = "yesterday"
    fields = {e.field for e in validate(record, load_schema())}
    assert fields == {"schema_version", "tranche_issue", "manifest/old_row_count", "detected_at"}


def test_nullable_fields_accept_null_and_ref_definitions_resolve() -> None:
    record = copy.deepcopy(VECTOR)
    cand = record["candidates"][0]
    cand.update(byte_verdict=None, byte_verdict_reason="old_fetch_failed", evidence=None,
                old_byte_sha256=None, old_byte_size=None)
    record["estimate"]["per_stage"] = []  # $defs/estimate: minItems 1
    assert {e.field for e in validate(record, load_schema())} == {"estimate/per_stage"}


def test_an_unimplemented_keyword_fails_closed_at_load(tmp_path: Path) -> None:
    schema = json.loads(schema_path().read_text())
    schema["properties"]["pages"]["properties"]["total"]["multipleOf"] = 2
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema))
    with pytest.raises(UnsupportedSchemaError, match="multipleOf"):
        load_schema(path)
