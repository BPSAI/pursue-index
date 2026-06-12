"""Tests for ``scripts/_video_ingest_core.py``.

Pure card-selection + DOD-id file-matching logic for the release
video/audio ingest, with the DVIDS scrape injected (no network). The
orchestration (R2/NAS upload) is exercised by the existing helper plumbing
and operator dry-runs; the meaningful, regressable logic is here.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _video_ingest_core as core  # noqa: E402


@dataclass
class FakeCard:
    card_id: str
    asset_type: str
    release_date: str
    dvids_video_id: str | None


# --- dod_id extraction ------------------------------------------------


def test_dod_id_bare_filename():
    assert core.dod_id("DOD_111764142.mp4") == "111764142"


def test_dod_id_resolution_suffixed_operator_file():
    # The operator's download carries a resolution/bitrate suffix.
    assert core.dod_id("DOD_111764142-1920x1080-9000k.mp4") == "111764142"


def test_dod_id_prefixed_filename():
    # Tranche-2 desktop files had a ``video_2605_`` prefix.
    assert core.dod_id("video_2605_DOD_111764142.mp4") == "111764142"


def test_dod_id_none_and_unmatched():
    assert core.dod_id(None) is None
    assert core.dod_id("not-a-dod-file.mp4") is None


# --- select_av_cards --------------------------------------------------


def _release3_cards():
    return [
        FakeCard("vid1", "VID", "6/12/26", "1010263"),
        FakeCard("aud1", "AUD", "6/12/26", "1010319"),
        FakeCard("pdf1", "PDF", "6/12/26", None),
        FakeCard("vidold", "VID", "5/22/26", "1007706"),
    ]


def test_select_av_includes_both_vid_and_aud_for_the_release():
    out = core.select_av_cards(_release3_cards(), "6/12/26")
    ids = {c.card_id for c in out}
    assert ids == {"vid1", "aud1"}  # PDF excluded, prior release excluded


def test_select_av_respects_explicit_asset_types():
    out = core.select_av_cards(_release3_cards(), "6/12/26", asset_types=("VID",))
    assert {c.card_id for c in out} == {"vid1"}


# --- match_cards_to_files (id-based, suffix-tolerant) -----------------


def test_match_by_dod_id_tolerates_resolution_suffix():
    cards = [FakeCard("vid1", "VID", "6/12/26", "1010263")]
    files = [Path("/d/DOD_111764142-1920x1080-9000k.mp4")]
    # DVIDS page references the bare DOD_<id>.mp4 for this dvids_video_id.
    resolver = lambda c: "DOD_111764142.mp4"  # noqa: E731
    matched, unmatched_cards, unmatched_files = core.match_cards_to_files(
        cards, files, resolver
    )
    assert matched == {"vid1": (cards[0], files[0])}
    assert unmatched_cards == []
    assert unmatched_files == []


def test_match_reports_card_with_no_dvids_id():
    cards = [FakeCard("vid1", "VID", "6/12/26", None)]
    matched, unmatched_cards, _unmatched_files = core.match_cards_to_files(
        cards, [], lambda c: None
    )
    assert matched == {}
    assert unmatched_cards == ["vid1"]


def test_match_reports_unmatched_card_when_file_absent():
    cards = [FakeCard("vid1", "VID", "6/12/26", "1010263")]
    files = [Path("/d/DOD_999999999.mp4")]
    resolver = lambda c: "DOD_111764142.mp4"  # noqa: E731
    matched, unmatched_cards, unmatched_files = core.match_cards_to_files(
        cards, files, resolver
    )
    assert matched == {}
    assert unmatched_cards == ["vid1"]
    assert unmatched_files == files


def test_match_reports_unmatched_file_when_no_card_claims_it():
    cards = [FakeCard("vid1", "VID", "6/12/26", "1010263")]
    files = [
        Path("/d/DOD_111764142.mp4"),
        Path("/d/DOD_222222222.mp4"),  # extra file, no card
    ]
    resolver = lambda c: "DOD_111764142.mp4"  # noqa: E731
    matched, unmatched_cards, unmatched_files = core.match_cards_to_files(
        cards, files, resolver
    )
    assert set(matched) == {"vid1"}
    assert unmatched_cards == []
    assert [p.name for p in unmatched_files] == ["DOD_222222222.mp4"]
