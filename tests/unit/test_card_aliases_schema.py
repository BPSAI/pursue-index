"""``data/card-aliases.json`` rows: base keys plus the OPTIONAL byte-change
evidence R7C.13 adds (``old_byte_sha256`` / ``new_byte_sha256`` /
``change_nature``). Rows with and without the evidence both validate, and
so does the committed file itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.alias_schema import CHANGE_NATURES, alias_row_errors
from pursue_index.ingest import append_aliases
from pursue_index.ingest_scope import load_aliases

REPO_ROOT = Path(__file__).resolve().parents[2]
D042 = ("a0f6663169c21caf", "ff3939f95d878062")


def _base() -> dict:
    return {"old_card_id": D042[0], "new_card_id": D042[1],
            "method": "operator_manual", "established": "2026-10-24T02:59:55+00:00"}


def test_row_without_byte_evidence_validates() -> None:
    assert alias_row_errors(_base()) == []


def test_row_with_all_byte_evidence_validates() -> None:
    row = {**_base(), "old_byte_sha256": "d5" * 32, "new_byte_sha256": "ca" * 32,
           "change_nature": "metadata-only"}
    assert alias_row_errors(row) == []


def test_change_nature_vocabulary() -> None:
    assert CHANGE_NATURES == ("metadata-only", "content-changed", "unknown")


def test_unknown_change_nature_is_rejected() -> None:
    errors = alias_row_errors({**_base(), "change_nature": "cosmetic"})
    assert errors and "change_nature" in errors[0]


@pytest.mark.parametrize("key", ["old_byte_sha256", "new_byte_sha256", "change_nature"])
def test_present_evidence_must_be_a_non_empty_string(key: str) -> None:
    assert alias_row_errors({**_base(), key: ""})
    assert alias_row_errors({**_base(), key: None})


@pytest.mark.parametrize("key", ["old_card_id", "new_card_id", "method", "established"])
def test_base_keys_are_required_strings(key: str) -> None:
    row = _base()
    row.pop(key)
    assert alias_row_errors(row)
    assert alias_row_errors({**_base(), key: 7})


def test_append_aliases_refuses_a_malformed_row(tmp_path: Path) -> None:
    path = tmp_path / "card-aliases.json"
    with pytest.raises(ValueError, match="change_nature"):
        append_aliases(path, [{**_base(), "change_nature": "cosmetic"}])
    assert not path.exists()
    append_aliases(path, [{**_base(), "change_nature": "metadata-only"}])
    assert load_aliases(path)[0]["change_nature"] == "metadata-only"


def test_committed_card_aliases_validates() -> None:
    rows = load_aliases(REPO_ROOT / "data" / "card-aliases.json")
    assert rows
    assert {i: alias_row_errors(r) for i, r in enumerate(rows) if alias_row_errors(r)} == {}


def test_committed_d042_row_carries_its_byte_change() -> None:
    rows = load_aliases(REPO_ROOT / "data" / "card-aliases.json")
    [d042] = [r for r in rows if (r["old_card_id"], r["new_card_id"]) == D042]
    assert d042["method"] == "operator_manual"
    assert d042["change_nature"] == "metadata-only"
    assert d042["old_byte_sha256"] == (
        "d52431b354af55b1e86cb454e61fd61993af3b023a38f2d9e014a9c9d18d16b4")
    assert d042["new_byte_sha256"] == (
        "ca9563779824e306f11393612fe6503f39877c6d5be03e77c875e928ee116b54")


def test_web_mirror_matches_the_committed_aliases() -> None:
    src = (REPO_ROOT / "data" / "card-aliases.json").read_bytes()
    assert (REPO_ROOT / "web" / "public" / "data" / "card-aliases.json").read_bytes() == src
