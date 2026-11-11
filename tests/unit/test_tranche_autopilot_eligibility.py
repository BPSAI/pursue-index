"""Eligibility matrix for ``pursue tranche autopilot`` (fail closed)."""

from __future__ import annotations

import pytest

from pursue_index.scrape.types import CardMetadata
from pursue_index.tranche_autopilot.eligibility import (
    ALLOWED_FIELDS,
    EXCLUDED_FIELDS,
    HEAVY_BUCKETS,
    ReceiptError,
    assess,
)
from pursue_index.tranche_autopilot.outcome import ExitCode
from tests.support.autopilot_fakes import OTHER_SHA, SHA, receipt, with_bucket


def _field_edit(field: str) -> dict:
    return receipt(field_only_changes=[
        {"card_id": "0123456789abcdef", "diffs": [{"field": field, "old": 1, "new": 2}]}])


def test_allowlisted_field_edit_is_eligible() -> None:
    verdict = assess(receipt(), SHA)
    assert verdict.verdict == "eligible"
    assert verdict.code is None
    assert verdict.fields_changed == ["description"]


def test_no_changes_at_all_is_eligible() -> None:
    doc = with_bucket(receipt(), "field_only_changes", [])
    assert assess(doc, SHA).verdict == "eligible"


@pytest.mark.parametrize("field", sorted(ALLOWED_FIELDS))
def test_every_allowlisted_field_is_eligible(field: str) -> None:
    assert assess(_field_edit(field), SHA).verdict == "eligible"


@pytest.mark.parametrize("field", [*sorted(EXCLUDED_FIELDS), "byte_sha256", "asset_size",
                                   "pdf_sha256", "brand_new_column"])
def test_non_allowlisted_field_is_ineligible(field: str) -> None:
    verdict = assess(_field_edit(field), SHA)
    assert verdict.code is ExitCode.INELIGIBLE
    assert any(field in r for r in verdict.reasons)


def test_allowlist_decides_every_manifest_field() -> None:
    # A new CardMetadata field must be placed on one list or the other.
    assert set(CardMetadata.model_fields) == ALLOWED_FIELDS | EXCLUDED_FIELDS
    assert not ALLOWED_FIELDS & EXCLUDED_FIELDS


def test_allowlist_never_touches_assets_or_bytes() -> None:
    for name in ALLOWED_FIELDS:
        assert not any(t in name for t in ("asset", "sha", "size", "card_id")), name


@pytest.mark.parametrize("bucket", HEAVY_BUCKETS)
def test_content_bucket_needs_a_lease(bucket: str) -> None:
    verdict = assess(with_bucket(receipt(), bucket, [{"new_card_id": "x"}]), SHA)
    assert verdict.code is ExitCode.NEEDS_LEASE
    assert verdict.verdict == "needs-lease"


def test_added_row_needs_a_lease() -> None:
    rows = [{"card_id": "c", "rows": [{"side": "added", "asset_type": "VID"}]}]
    assert assess(with_bucket(receipt(), "row_changes", rows), SHA).code is ExitCode.NEEDS_LEASE


def test_removed_row_is_ineligible() -> None:
    rows = [{"card_id": "c", "rows": [{"side": "removed", "asset_type": "VID"}]}]
    assert assess(with_bucket(receipt(), "row_changes", rows), SHA).code is ExitCode.INELIGIBLE


def test_removed_card_is_ineligible() -> None:
    doc = with_bucket(receipt(), "removed", [{"card_id": "c"}])
    assert assess(doc, SHA).code is ExitCode.INELIGIBLE


def test_unknown_nonzero_bucket_is_ineligible() -> None:
    doc = with_bucket(receipt(), "mystery_bucket", [{"x": 1}])
    verdict = assess(doc, SHA)
    assert verdict.code is ExitCode.INELIGIBLE
    assert "mystery_bucket=1" in verdict.reasons


def test_unknown_zero_bucket_is_fine() -> None:
    assert assess(with_bucket(receipt(), "mystery_bucket", []), SHA).verdict == "eligible"


def test_needs_lease_takes_precedence_over_ineligible() -> None:
    doc = with_bucket(_field_edit("asset_url"), "new_content", [{"new_card_id": "n"}])
    doc = with_bucket(doc, "removed", [{"card_id": "r"}])
    verdict = assess(doc, SHA)
    assert verdict.code is ExitCode.NEEDS_LEASE
    # The ineligible reasons are still reported alongside.
    assert "removed=1" in verdict.reasons
    assert any("asset_url" in r for r in verdict.reasons)


def test_wrong_tranche_receipt_is_refused() -> None:
    with pytest.raises(ReceiptError, match="does not match"):
        assess(receipt(sha=OTHER_SHA), SHA)


@pytest.mark.parametrize("bucket", ["row_changes", "removed", "field_only_changes"])
def test_receipt_missing_a_required_bucket_is_refused(bucket: str) -> None:
    doc = receipt()
    del doc["summary"][bucket]
    with pytest.raises(ReceiptError, match="lacks bucket"):
        assess(doc, SHA)


def test_summary_disagreeing_with_rows_is_refused() -> None:
    doc = receipt()
    doc["summary"]["field_only_changes"] = 0
    with pytest.raises(ReceiptError, match="disagrees"):
        assess(doc, SHA)


def test_nonzero_count_without_rows_is_refused() -> None:
    doc = receipt()
    doc["summary"]["removed"] = 2
    del doc["removed"]
    with pytest.raises(ReceiptError, match="disagrees"):
        assess(doc, SHA)


@pytest.mark.parametrize("bad", [-1, "1", True, None])
def test_non_integer_count_is_refused(bad: object) -> None:
    doc = receipt()
    doc["summary"]["removed"] = bad
    with pytest.raises(ReceiptError):
        assess(doc, SHA)


def test_field_change_without_field_name_is_refused() -> None:
    doc = receipt(field_only_changes=[{"card_id": "c", "diffs": [{"old": 1}]}])
    with pytest.raises(ReceiptError, match="field name"):
        assess(doc, SHA)
