"""Cross-language agreement for row pairing and reporting (Python half).

The /diff page (TypeScript) and this receipt generator pair manifest
rows -- and decide which changed fields to report -- independently. Both
read the SAME case file -- `tests/fixtures/row_pairing_cases.json` -- so
the two implementations agree by construction rather than through
hand-duplicated literals. The TypeScript half lives in
`web/src/components/row-pairing-fixture.test.ts`.

`cases` pins pairing; `reporting_cases` pins what each side reports once
two rows are paired. Pairing agreement alone is not enough: a field that
one side compares and the other does not is a mutation that reaches the
committed receipt while the published page renders nothing for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.tranche import field_diff  # noqa: E402
from pursue_index.tranche_rows import pair_rows_by_card_id  # noqa: E402

_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "row_pairing_cases.json"
_FIXTURE_DATA: dict[str, Any] = json.loads(_FIXTURE.read_text())
_CASES: list[dict[str, Any]] = _FIXTURE_DATA["cases"]
_REPORTING_CASES: list[dict[str, Any]] = _FIXTURE_DATA["reporting_cases"]


def _index_of(rows: list[dict[str, Any]], row: dict[str, Any]) -> int:
    """Position of `row` in `rows` by identity, not equality -- two rows
    in one case can compare equal while being distinct manifest rows."""
    for i, candidate in enumerate(rows):
        if candidate is row:
            return i
    return -1


def test_fixture_is_non_trivial() -> None:
    assert len(_CASES) >= 8
    assert all(c["name"] for c in _CASES)


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_pairing_matches_shared_fixture(case: dict[str, Any]) -> None:
    prev, curr = case["prev"], case["curr"]
    pairs, unpaired = pair_rows_by_card_id(prev, curr)

    actual_pairs = sorted(
        (_index_of(prev, p["prev"]), _index_of(curr, p["curr"])) for p in pairs
    )
    assert all(a >= 0 and b >= 0 for a, b in actual_pairs)
    assert actual_pairs == sorted(tuple(p) for p in case["expected_pairs"])

    actual_unpaired = sorted(
        (
            u["side"],
            _index_of(prev if u["side"] == "prev" else curr, u["row"]),
        )
        for u in unpaired
    )
    assert all(i >= 0 for _, i in actual_unpaired)
    assert actual_unpaired == sorted(
        (u["side"], u["index"]) for u in case["expected_unpaired"]
    )


def _group_by_card_id(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["card_id"], []).append(row)
    return groups


def _reported_fields(
    prev: list[dict[str, Any]], curr: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """{card_id: sorted changed field names} across a whole snapshot pair."""
    prev_groups = _group_by_card_id(prev)
    curr_groups = _group_by_card_id(curr)
    out: dict[str, list[str]] = {}
    for card_id, prev_rows in prev_groups.items():
        curr_rows = curr_groups.get(card_id)
        if curr_rows is None:
            continue
        fields = sorted(d["field"] for d in field_diff(prev_rows, curr_rows))
        if fields:
            out[card_id] = fields
    return out


@pytest.mark.parametrize(
    "case", _REPORTING_CASES, ids=[c["name"] for c in _REPORTING_CASES]
)
def test_reported_fields_match_shared_fixture(case: dict[str, Any]) -> None:
    expected = {k: sorted(v) for k, v in case["expected_changed_fields"].items()}
    assert _reported_fields(case["prev"], case["curr"]) == expected
