"""Round 3: the NTRS claim_count unit, the row key of a row with no card_id, per-file lists."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.ntrs_source import CardSearch
from pursue_index.ntrs_source import build_output as ntrs_output
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import build_report
from pursue_index.resolved_claim import ResolutionSource, ResolvedClaim
from pursue_index.row_key import row_keys

_DOC = (Path(__file__).resolve().parents[2] / "docs" / "provenance-artifacts-schema.md").read_text()
_FBI = "This file was partially posted on the FBI vault; some pages missing."


def _row(card_id: str | None, title: str, **fields: Any) -> dict[str, Any]:
    row = {"title": title, "agency": "DOW", "release_date": "5/8/2026", **fields}
    if card_id is not None:
        row["card_id"] = card_id
    return row


# --- (a) NTRS claim_count --------------------------------------------------------


def _claim(card_id: str, row_key: str) -> ResolvedClaim:
    return ResolvedClaim(
        card_id=card_id,
        row_key=row_key,
        tier=ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
        source=ResolutionSource.NTRS_METADATA,
        identifier_kind="ntrs_citation_id",
        identifier_value="19700001234",
        artifact_url="https://ntrs.nasa.gov/citations/19700001234",
        established_date=date(1970, 1, 2),
        date_basis=DateBasis.PUBLISHER_DATE,
    )


def test_ntrs_claim_count_is_the_stored_claim_records_not_rows() -> None:
    day = date(2026, 1, 1)
    searches = [
        CardSearch("aaaa", "q", day, "claim", _claim("aaaa", "aaaa#0"), row_key="aaaa#0"),
        CardSearch("aaaa", "q", day, "no_copy_found", row_key="aaaa#1"),
        CardSearch("bbbb", "q", day, "no_copy_found", row_key="bbbb#0"),
    ]
    out = ntrs_output({"cards": [_row("aaaa", "x")] * 3}, searches, {})
    assert out["claim_count"] == len(out["claims"]) == 1
    assert out["claim_count"] != out["searched_row_count"] == len(out["searches"]) == 3


def test_the_doc_ntrs_table_gives_claim_count_its_unit() -> None:
    section = _DOC.split("## `ntrs-claims.json`")[1].split("## Coverage report")[0]
    lines = [ln for ln in section.splitlines() if ln.startswith("|") and "`claim_count`" in ln]
    assert lines, "no claim_count row in the NTRS table"
    cells = [c.strip() for c in lines[0].strip("|").split("|")]
    assert cells[2] == "claim" and "stored" in cells[3] and "claims[]" in cells[3]
    assert "unchanged from v1" in cells[3].lower()


# --- (b) row_key of a row with no card_id ----------------------------------------


def test_card_id_less_rows_get_well_defined_unique_stable_keys() -> None:
    cards = [_row("aaaa", "A"), _row(None, "no key"), _row("", "empty"), _row("aaaa", "A2"), _row(None, "again")]
    keys = row_keys(cards)
    assert keys == row_keys(cards)
    assert len(set(keys)) == len(keys) == 5
    for key in keys:
        file_part, _, n = key.rpartition("#")
        assert file_part and n.isdigit(), key
    assert keys[0] == "aaaa#0" and keys[3] == "aaaa#1"
    assert [k.rpartition("#")[2] for k in keys] == ["0", "0", "0", "1", "0"]


def test_a_card_id_less_row_key_is_the_same_in_every_writer() -> None:
    cards = [_row(None, "one"), _row(None, "two")]
    keys = row_keys(cards)
    assert [c.row_key for c in bucket({"cards": cards}).cards] == keys
    assert [o.row_key for o in build_report({"cards": cards}).outcomes] == keys


def test_the_doc_defines_row_key_for_every_row() -> None:
    assert "{file_key}#{n}" in _DOC


# --- (c) per-file lists include card_id-less files --------------------------------


def test_per_file_lists_include_card_id_less_files_and_match_their_counts() -> None:
    cards = [
        _row("aaaa", "A1", incident_date="2022-05-06"),
        _row(None, "modern", incident_date="2022-05-06"),
        _row(None, "undated"),
        _row(None, "flagged", incident_date="1952-07-01", description=_FBI),
    ]
    keys = row_keys(cards)
    files = [k.rpartition("#")[0] for k in keys]
    manifest = {"cards": cards}
    era = build_output(manifest, bucket(manifest))
    assert files[1] in era["no_prior_release_files"] and files[0] in era["no_prior_release_files"]
    assert era["no_prior_release_file_count"] == len(era["no_prior_release_files"])
    report = build_report(manifest).to_dict()
    assert files[2] in report["unresolved_files"]
    assert files[3] in report["page_image_flagged_files"]
    assert report["file_count"] == era["file_count"] == 4
    assert report["unresolved"] == len(report["unresolved_files"])
    assert report["page_image_flagged"] == len(report["page_image_flagged_files"])
    for name in ("no_prior_release_files", "unresolved_files", "page_image_flagged_files"):
        values = era.get(name, report.get(name))
        assert len(values) == len(set(values)), name
