"""The vendored tranche-ready schema and its Release-7 test vector (R7C.31).

pursue-opsec is the single owner of the tranche-ready contract
(``plans/specs/tranche-ready.schema.json`` and
``plans/specs/tranche-ready-096ef.example.json``, R7C.29). This repo
vendors both byte-for-byte -- ``schemas/tranche-ready.schema.json`` and
``tests/fixtures/tranche-ready-096ef.json`` -- and never edits them. These
tests read only this repository: they pin each vendored file's sha256 (the
values pursue-opsec's copies hashed to when they were vendored) and that the
schema, the vector and this test all name the same ``schema_version``.

Changing the schema means bumping ``schema_version`` upstream and updating
every pin in the same change (the spec's own procedure); a drift on either
side fails here first.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "tranche-ready.schema.json"
VECTOR_PATH = REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json"

# Pinned from pursue-opsec's plans/specs/ copies at the commit this repo
# vendored them from (pursue-opsec-staging 5b89ade, R7C.29).
PINNED_SCHEMA_VERSION = "1.0.0"
# The schema pin is the sha256 of pursue-opsec's copy as of the opsec commit
# that mirrored these bytes, so this test detects drift on EITHER side: edit
# the schema here without opsec (or the reverse) and the pin stops matching.
# History: 7fb15b81... carried the maxLength bounds (titles 512, signals 256,
# doc_id 64 + pattern); the pin below adds the maxItems caps (stop_reasons,
# fallback_cards, changed_objects 200; continuity_signals 50). opsec must
# mirror this exact file, then this comment's "as of" commit is updated.
_UPSTREAM_SCHEMA_SHA256 = "a231f58e6a6115f91f0fc932956b63be44c2af88e64fe357c09b2f83c5e673d0"
_UPSTREAM_VECTOR_SHA256 = "46ae4c7e4e590b637cbe4aa527817ccc017b2ac52592346c046de7dc4cb95884"


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_version_of_schema() -> str:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema["properties"]["schema_version"]["const"]


def _schema_version_of_vector() -> str:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))["schema_version"]


def test_vendored_schema_is_byte_identical_to_pursue_opsecs() -> None:
    assert _sha256_of(SCHEMA_PATH) == _UPSTREAM_SCHEMA_SHA256


def test_vendored_vector_is_byte_identical_to_pursue_opsecs() -> None:
    assert _sha256_of(VECTOR_PATH) == _UPSTREAM_VECTOR_SHA256


def test_schema_vector_and_this_pin_carry_the_same_schema_version() -> None:
    assert _schema_version_of_schema() == PINNED_SCHEMA_VERSION
    assert _schema_version_of_vector() == PINNED_SCHEMA_VERSION
    assert _schema_version_of_schema() == _schema_version_of_vector()


def test_the_vendored_copies_are_read_from_this_repo_only() -> None:
    """Neither path may reach outside this checkout (no sibling-repo read)."""
    for path in (SCHEMA_PATH, VECTOR_PATH):
        assert path.resolve().is_relative_to(REPO_ROOT)
