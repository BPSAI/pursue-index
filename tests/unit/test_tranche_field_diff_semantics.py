"""Comparison semantics `field_diff` shares with the /diff page.

`field_diff` (src/pursue_index/tranche.py) and `fieldOnlyChanges`
(web/src/components/diff-helpers.ts) must agree on WHICH differences
between two paired rows count as a reportable change, not merely on how
rows pair. Three rules govern that, and each exists because breaking it
put a wrong number in front of a reader:

  1. Absent and explicitly-null compare equal, so a snapshot schema
     addition is not an edit.
  2. Boolean fields compare by truthiness, so introducing a boolean
     column is not an edit on every row that lacks it.
  3. Locally-curated fields are excluded outright, because they describe
     our own editorial work rather than an upstream change.

The cross-language half of rules 1 and 2 is pinned by the shared fixture
(tests/fixtures/row_pairing_cases.json); rule 3's two field sets are
pinned identical by web/src/components/diff-helpers.test.ts. This file
pins the Python behaviour itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pursue_index.tranche import LOCAL_CURATION_FIELDS, field_diff  # noqa: E402


def _row(card_id: str = "aa11", **extras: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "card_id": card_id,
        "asset_type": "PDF",
        "title": "Mission Report",
        "asset_url": "https://x/a.pdf",
        "dvids_video_id": None,
        "video_title": None,
    }
    base.update(extras)
    return base


def _fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [d["field"] for d in field_diff([old], [new])]


# --- rule 3: locally-curated fields are never an upstream change ---------


def test_local_curation_set_is_the_expected_eight_fields() -> None:
    assert LOCAL_CURATION_FIELDS == {
        "display_date",
        "display_date_range",
        "display_date_abstention",
        "display_date_approved_at",
        "display_date_curator",
        "display_date_evidence",
        "display_date_evidence_card_ref",
        "manifest_incident_date_raw",
    }


def test_display_date_change_is_not_reported_as_an_upstream_change() -> None:
    """A curator approving a display date is our work, not war.gov's."""
    old = _row(display_date=None)
    new = _row(display_date="2023-10-24")
    assert _fields(old, new) == []


def test_every_local_curation_field_is_excluded() -> None:
    for field in LOCAL_CURATION_FIELDS:
        old = _row(**{field: None})
        new = _row(**{field: "curated-value"})
        assert _fields(old, new) == [], f"{field} must not be reported"


# --- rule 2: boolean fields compare by truthiness ------------------------


def test_introducing_a_boolean_column_is_not_a_change() -> None:
    """A snapshot predating `featured` has no value for it; the one after
    carries an explicit False on every unflagged row. Comparing those with
    `!=` flagged the whole corpus (210 cards on 6be2c64e->5216a20b)."""
    old = _row()
    new = _row(featured=False)
    assert _fields(old, new) == []


def test_explicit_none_to_false_on_a_boolean_field_is_not_a_change() -> None:
    old = _row(featured=None, redacted=None)
    new = _row(featured=False, redacted=False)
    assert _fields(old, new) == []


def test_a_boolean_actually_being_set_is_still_reported() -> None:
    """The rule narrows to the introduction case: False->True is a real
    upstream editorial act and must still reach the receipt."""
    assert _fields(_row(featured=False), _row(featured=True)) == ["featured"]
    assert _fields(_row(redacted=True), _row(redacted=False)) == ["redacted"]


def test_truthiness_rule_applies_only_to_the_declared_boolean_fields() -> None:
    """A non-boolean field must keep exact comparison — collapsing e.g.
    an empty-string title into None would hide a real deletion."""
    assert _fields(_row(incident_location=""), _row(incident_location=None)) == [
        "incident_location"
    ]


def test_a_real_upstream_field_still_reports_alongside_curation_fields() -> None:
    """Excluding curation fields must not suppress a genuine edit on the
    same row — the two are decided per field, not per row."""
    old = _row(display_date=None, incident_location="Iraq")
    new = _row(display_date="2023-10-24", incident_location="Syria")
    assert _fields(old, new) == ["incident_location"]
