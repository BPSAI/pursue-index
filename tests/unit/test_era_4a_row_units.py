"""§4a is a per-row baseline, so it is compared against per-row era counts.

``REFERENCE_4A`` was computed over rows of an earlier corpus. The per-file
``era_counts`` answer a different question, so the comparison must read
``era_row_counts`` and say which unit it used.
"""

from __future__ import annotations

from typing import Any

from pursue_index.era_bucketing import REFERENCE_4A, bucket, build_output


def _row(card_id: str, **fields: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": card_id, "agency": "DOW", "release_date": "5/8/2026", **fields}


def _manifest() -> dict[str, Any]:
    # One file of three modern rows, and a mixed file: files and rows tally differently.
    return {
        "cards": [
            _row("aaaa", incident_date="2022-05-06"),
            _row("aaaa", incident_date="2022-05-06"),
            _row("aaaa", incident_date="2022-05-06"),
            _row("bbbb", incident_date="2022-05-06"),
            _row("bbbb"),
        ]
    }


def test_the_comparison_reads_row_counts_and_names_the_unit() -> None:
    manifest = _manifest()
    result = bucket(manifest)
    recon = build_output(manifest, result)["reconciliation_4a"]
    assert recon["unit"] == "rows"
    assert result.era_row_counts["2015_plus"] == 4 and result.era_counts["2015_plus"] == 1
    assert recon["current"]["2015_plus"] == result.era_row_counts["2015_plus"] == 4
    assert recon["current"]["undated"] == result.era_row_counts["undated"] == 1
    assert recon["delta"]["2015_plus"] == 4 - REFERENCE_4A["2015_plus"]


def test_the_comparison_never_carries_a_mixed_bucket() -> None:
    recon = build_output(_manifest(), bucket(_manifest()))["reconciliation_4a"]
    assert set(recon["current"]) == set(REFERENCE_4A) == set(recon["delta"])
