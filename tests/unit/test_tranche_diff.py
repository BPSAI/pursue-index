"""Tests for `scripts/tranche_diff.py` and `pursue_index.tranche` helpers.

The diff analyzer is the gating sensor for the operator's ingest approval —
it tells the operator, before any deployed-state change, exactly how the
incoming tranche differs from the currently-deployed manifest and which
cards in the new tranche are safe to alias as renames vs. which need
manual review (suspicious replacements) vs. which are genuinely-new
content.

Test coverage targets:
  - byte_sha-driven classification (Class A confirmed renames)
  - title-continuity heuristics (Class C suspicious replacements)
  - net-new detection (Class B)
  - removed-card detection (post-rename-matching)
  - field-only changes among unchanged card_ids
  - report serialization (JSON + Markdown)
  - safety on degenerate inputs (empty manifests, missing fields)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for p in (_SRC, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from pursue_index.tranche import (  # noqa: E402
    extract_numeric_id,
    find_title_continuity,
    levenshtein,
)
import tranche_diff  # noqa: E402


# --- Levenshtein ---


def test_levenshtein_identical_zero() -> None:
    assert levenshtein("abc", "abc") == 0


def test_levenshtein_simple_substitution() -> None:
    assert levenshtein("kitten", "sitting") == 3


def test_levenshtein_empty_strings() -> None:
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "") == 3
    assert levenshtein("", "") == 0


def test_levenshtein_bracket_rename_close() -> None:
    # The actual NASC-State case: filename gained brackets around the date.
    a = "59_214434_sp_16_7.18.1963.pdf"
    b = "59_214434_sp_16_[7.18.1963].pdf"
    assert levenshtein(a, b) == 2  # +2 brackets


# --- Numeric ID extraction ---


def test_numeric_id_from_dow_uap_d33() -> None:
    assert extract_numeric_id("DOW-UAP-D33, Mission Report, Greece, October 2023") == 33


def test_numeric_id_zero_padded_d003() -> None:
    assert extract_numeric_id("NASA-UAP-D003, Apollo 11 Technical Crew Debriefing, 1969") == 3


def test_numeric_id_pr_prefix() -> None:
    assert extract_numeric_id("DOW-UAP-PR032, Unresolved UAP Report, Syria, October 2024") == 32


def test_numeric_id_vm_prefix() -> None:
    assert extract_numeric_id("NASA-UAP-VM4, Apollo 12, 1969") == 4


def test_numeric_id_no_match() -> None:
    assert extract_numeric_id("FBI Photo B021") is None  # B is not in the (D|VM|PR|VID) pattern
    assert extract_numeric_id("Some random title") is None
    assert extract_numeric_id("") is None


def test_numeric_id_d33_and_d033_collide() -> None:
    """The pattern's whole point: D33 and D033 must map to the same int."""
    assert extract_numeric_id("DOW-UAP-D33, Mission Report, Greece, October 2023") == \
        extract_numeric_id("DOW-UAP-D033, Mission Report, Greece, October 2023")


# --- Title-continuity heuristics ---


def _card(card_id: str, **kw) -> dict:
    """Build a manifest card dict with sensible defaults."""
    base = {
        "card_id": card_id,
        "title": "",
        "asset_type": "PDF",
        "agency": None,
        "incident_date": None,
        "incident_location": None,
        "asset_filename": None,
        "asset_url": None,
        "video_title": None,
    }
    base.update(kw)
    return base


def test_continuity_matches_same_agency_and_date() -> None:
    new = _card("new1", agency="DOW", incident_date="10/15/2023", title="X")
    old = _card("old1", agency="DOW", incident_date="10/15/2023", title="Y")
    matches = find_title_continuity(new, [old])
    assert len(matches) == 1
    assert any("agency" in r and "incident_date" in r for r in matches[0]["reasons"])


def test_continuity_skips_n_a_dates() -> None:
    new = _card("new1", agency="DOW", incident_date="N/A")
    old = _card("old1", agency="DOW", incident_date="N/A")
    matches = find_title_continuity(new, [old])
    # Must NOT trigger purely on agency + "N/A" — too unspecific.
    assert all("agency + same incident_date" not in r for m in matches for r in m["reasons"])


def test_continuity_matches_same_location() -> None:
    new = _card("new1", incident_location="Aegean Sea", title="X")
    old = _card("old1", incident_location="Aegean Sea", title="Y")
    matches = find_title_continuity(new, [old])
    assert any("incident_location" in r for r in matches[0]["reasons"])


def test_continuity_matches_numeric_id() -> None:
    new = _card("new1", title="DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024")
    old = _card("old1", title="DOW-UAP-D33, Mission Report, Greece, October 2023")
    matches = find_title_continuity(new, [old])
    assert len(matches) == 1
    assert any("numeric id 33" in r for r in matches[0]["reasons"])


def test_continuity_matches_filename_levenshtein() -> None:
    new = _card("new1", asset_filename="59_214434_sp_16_[7.18.1963].pdf")
    old = _card("old1", asset_filename="59_214434_sp_16_7.18.1963.pdf")
    matches = find_title_continuity(new, [old])
    assert any("Levenshtein" in r or "filename" in r for r in matches[0]["reasons"])


def test_continuity_no_match_when_truly_unrelated() -> None:
    new = _card("new1", agency="NASA", incident_date="1969", title="Apollo 11")
    old = _card("old1", agency="FBI", incident_date="1947", title="Roswell teletype")
    assert find_title_continuity(new, [old]) == []


def test_continuity_levenshtein_distance_over_threshold_no_match() -> None:
    new = _card("new1", asset_filename="apollo_11_debriefing_volume_one.pdf")
    old = _card("old1", asset_filename="fbi_section_6_section.pdf")
    matches = find_title_continuity(new, [old])
    # No reasons should fire — way over Levenshtein 8.
    assert matches == [] or all("Levenshtein" not in r for m in matches for r in m["reasons"])


# --- diff_tranches orchestration ---


def _manifest(cards: list[dict]) -> dict:
    return {"csv_sha256": "fake", "cards": cards}


def _registry_with(*entries: dict) -> dict[str, list[dict]]:
    """Build a {card_id: [rows]} registry mimicking r2_archive_assets.load_registry()."""
    out: dict[str, list[dict]] = {}
    for e in entries:
        out.setdefault(e["card_id"], []).append(e)
    return out


def test_diff_finds_class_a_byte_collision() -> None:
    """New card with byte_sha colliding with an existing registry entry → renames_confirmed."""
    old_manifest = _manifest([
        _card("aa11", asset_url="https://x/old.pdf", asset_filename="old.pdf",
              title="59_64634_711.5612[7-2852"),
    ])
    new_manifest = _manifest([
        _card("9e22", asset_url="https://x/new.pdf", asset_filename="new.pdf",
              title="59_214434_SP 16 [7.18.1963]"),
    ])
    registry = _registry_with(
        {"card_id": "aa11", "byte_sha256": "deadbeef" * 8},
    )
    # Fake fetcher: new card's bytes hash to the same sha as old's registry row.
    fake_fetch = {"https://x/new.pdf": "deadbeef" * 8}

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest,
        new_manifest=new_manifest,
        registry=registry,
        fetch_byte_sha=lambda url: fake_fetch.get(url),
    )

    assert len(result["renames_confirmed"]) == 1
    r = result["renames_confirmed"][0]
    assert r["old_card_id"] == "aa11"
    assert r["new_card_id"] == "9e22"
    assert r["byte_sha256"] == "deadbeef" * 8
    # aa11 must NOT appear in removed — it was matched as a rename.
    assert all(c["card_id"] != "aa11" for c in result["removed"])


def test_diff_finds_class_b_net_new_content() -> None:
    """New card with no byte collision and no title continuity → new_content."""
    old_manifest = _manifest([])
    new_manifest = _manifest([
        _card("ff00", asset_url="https://x/photo.pdf",
              asset_filename="fbi-photo-b21.pdf", title="FBI Photo B021"),
    ])
    fake_fetch = {"https://x/photo.pdf": "01" * 32}

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    assert len(result["new_content"]) == 1
    assert result["new_content"][0]["new_card_id"] == "ff00"


def test_diff_finds_class_c_suspicious_replacement() -> None:
    """New card with new byte_sha AND title continuity → quarantined."""
    old_manifest = _manifest([
        _card("aa11", title="DOW-UAP-D33, Mission Report, Greece, October 2023",
              agency="DOW", incident_date="10/24/2023",
              asset_url="https://x/d33.pdf"),
    ])
    new_manifest = _manifest([
        _card("9e22", title="DOW-UAP-PR033, Unresolved UAP Report, Syria, October 2024",
              agency="DOW", incident_date="10/24/2023",
              asset_url="https://x/pr033.pdf"),
    ])
    fake_fetch = {"https://x/pr033.pdf": "ff" * 32}  # different bytes

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    assert len(result["quarantined"]) == 1
    q = result["quarantined"][0]
    assert q["new_card_id"] == "9e22"
    assert "aa11" in q["matched_against"]


def test_diff_finds_removed_unmatched_old_cards() -> None:
    """Old card_ids that don't match any rename via byte_sha → removed list."""
    old_manifest = _manifest([
        _card("aa11", asset_url="https://x/gone.pdf"),
    ])
    new_manifest = _manifest([])  # empty new

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=lambda url: None,
    )
    assert len(result["removed"]) == 1
    assert result["removed"][0]["card_id"] == "aa11"


def test_diff_field_only_changes_same_card_id() -> None:
    """Same card_id present in both manifests, but a field changed."""
    old_manifest = _manifest([_card("aa11", title="X", description="old desc")])
    new_manifest = _manifest([_card("aa11", title="X", description="NEW desc")])

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=lambda url: None,
    )
    assert len(result["field_only_changes"]) == 1
    fc = result["field_only_changes"][0]
    assert fc["card_id"] == "aa11"
    assert any(d["field"] == "description" for d in fc["diffs"])


def test_diff_summary_counts() -> None:
    old_manifest = _manifest([
        _card("aa11", asset_url="https://x/renamed.pdf"),  # will be renamed
        _card("bb22", asset_url="https://x/gone.pdf"),      # will be removed
    ])
    new_manifest = _manifest([
        _card("9e33", asset_url="https://x/new.pdf"),       # rename target of aa11
        _card("ff44", asset_url="https://x/netnew.pdf"),    # net new
    ])
    registry = _registry_with({"card_id": "aa11", "byte_sha256": "ab" * 32})
    fake_fetch = {
        "https://x/new.pdf": "ab" * 32,    # collision → rename
        "https://x/netnew.pdf": "cd" * 32, # new
    }

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry=registry, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    s = result["summary"]
    assert s["renames_confirmed"] == 1
    assert s["new_content"] == 1
    assert s["quarantined"] == 0
    assert s["removed"] == 1
    assert s["field_only_changes"] == 0


# --- Report writers ---


def test_render_markdown_includes_all_sections(tmp_path: Path) -> None:
    diff = {
        "tranche_sha256": "abc123",
        "prior_manifest": "data/manifests/snapshots/old.json",
        "summary": {"renames_confirmed": 1, "new_content": 1, "quarantined": 1,
                    "removed": 1, "field_only_changes": 1},
        "renames_confirmed": [{"old_card_id": "aa11", "new_card_id": "9e22",
                               "byte_sha256": "ff" * 32, "old_title": "X", "new_title": "Y"}],
        "new_content": [{"new_card_id": "ff44", "title": "Z", "byte_sha256": "cd" * 32,
                         "asset_filename": "z.pdf"}],
        "quarantined": [{"new_card_id": "9e33", "matched_against": ["bb22"],
                         "reasons": ["matching numeric id 33"],
                         "new_byte_sha256": "ee" * 32}],
        "removed": [{"card_id": "cc55", "title": "Removed", "asset_url": "https://x/r.pdf"}],
        "field_only_changes": [{"card_id": "dd66", "diffs": [{"field": "description",
                                                              "old": "x", "new": "y"}]}],
    }
    md = tranche_diff.render_markdown(diff)
    # Every section should appear as a header.
    for header in ("Renames confirmed", "Net-new content", "Quarantined",
                   "Removed", "Field-only changes"):
        assert header in md, f"missing section: {header}"
    # The summary counts should appear.
    assert "1" in md


def test_render_json_round_trip() -> None:
    import json
    diff = {
        "tranche_sha256": "abc",
        "summary": {"renames_confirmed": 0, "new_content": 0, "quarantined": 0,
                    "removed": 0, "field_only_changes": 0},
        "renames_confirmed": [], "new_content": [], "quarantined": [],
        "removed": [], "field_only_changes": [],
    }
    s = tranche_diff.render_json(diff)
    parsed = json.loads(s)
    assert parsed["tranche_sha256"] == "abc"
    assert parsed["summary"]["renames_confirmed"] == 0


# --- Safety on degenerate inputs ---


def test_diff_handles_card_without_asset_url() -> None:
    """VID cards have asset_url=None; should not error, should not fetch."""
    old_manifest = _manifest([])
    new_manifest = _manifest([_card("vid1", asset_url=None, title="VID-1", asset_type="VID")])
    fetched_urls: list[str] = []
    def fake_fetch(url):
        fetched_urls.append(url)
        return None

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry={}, fetch_byte_sha=fake_fetch,
    )
    assert fetched_urls == []
    # With no asset_url and no continuity match, this is class B (net-new).
    assert len(result["new_content"]) == 1


def test_diff_handles_empty_manifests() -> None:
    result = tranche_diff.diff_tranches(
        old_manifest=_manifest([]), new_manifest=_manifest([]),
        registry={}, fetch_byte_sha=lambda url: None,
    )
    assert result["summary"]["renames_confirmed"] == 0
    assert result["summary"]["new_content"] == 0
    assert result["summary"]["removed"] == 0


# --- Restoration detection (Class D) ---
#
# A "restoration" is an added card_id that was previously archived in
# our registry (typically via r2_pin_removed.py for a /removed card)
# and is now reappearing upstream. Three sub-classes:
#   - restored_unchanged  — bytes match the pinned byte_sha (safe)
#   - restored_modified   — bytes differ from the pinned byte_sha
#                           (SUSPICIOUS — possible tampering disguised
#                           as restoration)
#   - restored_unknown    — no asset_url to fetch bytes from (needs
#                           operator inspection)


def test_diff_restored_unchanged_when_bytes_match_pinned() -> None:
    """Previously preserved card_id reappears upstream with same bytes."""
    pinned_sha = "aa" * 32
    registry = _registry_with(
        {"card_id": "13f8", "byte_sha256": pinned_sha, "preserved": True,
         "fetched_at": "2026-05-12T14:44:09+00:00"},
    )
    old_manifest = _manifest([])  # card was removed in prior tranche
    new_manifest = _manifest([
        _card("13f8", asset_url="https://x/restored.pdf",
              title="FBI 62-HQ-83894 Section 6"),
    ])
    fake_fetch = {"https://x/restored.pdf": pinned_sha}

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry=registry, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    assert len(result["restored_unchanged"]) == 1
    assert result["restored_unchanged"][0]["new_card_id"] == "13f8"
    # And it must NOT also appear in new_content or quarantined.
    assert result["new_content"] == []
    assert result["quarantined"] == []


def test_diff_restored_modified_when_bytes_differ_from_pinned() -> None:
    """SUSPICIOUS: preserved card_id reappears with DIFFERENT bytes."""
    pinned_sha = "aa" * 32
    actual_new_sha = "ff" * 32
    registry = _registry_with(
        {"card_id": "13f8", "byte_sha256": pinned_sha, "preserved": True,
         "fetched_at": "2026-05-12T14:44:09+00:00"},
    )
    old_manifest = _manifest([])
    new_manifest = _manifest([
        _card("13f8", asset_url="https://x/restored.pdf",
              title="FBI 62-HQ-83894 Section 6"),
    ])
    fake_fetch = {"https://x/restored.pdf": actual_new_sha}

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry=registry, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    assert len(result["restored_modified"]) == 1
    r = result["restored_modified"][0]
    assert r["new_card_id"] == "13f8"
    assert r["pinned_byte_sha256"] == pinned_sha
    assert r["new_byte_sha256"] == actual_new_sha


def test_diff_restored_unknown_when_no_asset_url() -> None:
    """VID-style card with asset_url=None but card_id is in registry."""
    registry = _registry_with(
        {"card_id": "13f8", "byte_sha256": "aa" * 32, "preserved": True,
         "fetched_at": "2026-05-12T14:44:09+00:00"},
    )
    old_manifest = _manifest([])
    new_manifest = _manifest([_card("13f8", asset_url=None, asset_type="VID")])

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry=registry, fetch_byte_sha=lambda url: None,
    )
    assert len(result["restored_unknown"]) == 1


def test_diff_restoration_takes_precedence_over_class_a() -> None:
    """If new_card_id is in registry, classify as restoration even if
    sha would otherwise match another card_id under Class A."""
    shared_sha = "aa" * 32
    registry = _registry_with(
        {"card_id": "13f8", "byte_sha256": shared_sha, "preserved": True,
         "fetched_at": "2026-05-12T14:44:09+00:00"},
        {"card_id": "9999", "byte_sha256": shared_sha,
         "fetched_at": "2026-05-12T14:00:00+00:00"},
    )
    old_manifest = _manifest([])
    new_manifest = _manifest([_card("13f8", asset_url="https://x/r.pdf")])
    fake_fetch = {"https://x/r.pdf": shared_sha}

    result = tranche_diff.diff_tranches(
        old_manifest=old_manifest, new_manifest=new_manifest,
        registry=registry, fetch_byte_sha=lambda url: fake_fetch.get(url),
    )
    assert len(result["restored_unchanged"]) == 1
    assert len(result["renames_confirmed"]) == 0
