"""Tests for the ingest skip-set helpers in ``_ingest_tranche2_helpers``.

``already_archived_card_ids`` treats a card as done if it has *any* mp4
row (archive OR current). That is too aggressive for cards whose bytes
are archived but have no ``<card_id>.mp4`` current pointer yet (e.g. the
Release-1 PDF+video cards): re-ingest must be allowed to add the pointer.
``already_current_pointer_card_ids`` narrows the skip set to cards that
truly already serve an mp4 current pointer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _ingest_tranche2_helpers as helpers  # noqa: E402


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "registry.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def test_current_pointer_helper_ignores_archive_only_rows(tmp_path: Path):
    reg = _write(
        tmp_path,
        [
            # archive-only mp4 (no current pointer) — NOT done
            {"card_id": "aaa", "archive_key": "archive/x.mp4", "current_key": None},
            # current-pointer mp4 — done
            {"card_id": "bbb", "archive_key": "archive/y.mp4", "current_key": "bbb.mp4"},
            # pdf current pointer only — not an mp4, NOT done
            {"card_id": "ccc", "archive_key": "archive/z.pdf", "current_key": "ccc.pdf"},
        ],
    )
    assert helpers.already_current_pointer_card_ids(reg) == {"bbb"}


def test_archive_helper_still_counts_archive_only(tmp_path: Path):
    # Existing helper is unchanged: archive-only rows still count as done.
    # Real archive-only rows omit ``current_key`` entirely (not null).
    reg = _write(
        tmp_path,
        [{"card_id": "aaa", "archive_key": "archive/x.mp4"}],
    )
    assert helpers.already_archived_card_ids(reg) == {"aaa"}
    assert helpers.already_current_pointer_card_ids(reg) == set()


def test_current_pointer_helper_missing_file(tmp_path: Path):
    assert helpers.already_current_pointer_card_ids(tmp_path / "nope.jsonl") == set()


# --- DVIDS URL kind (Release-5 finding) -------------------------------
#
# `build_registry_entry` derived the DVIDS path segment from the
# government's asset_type: AUD -> /audio/, everything else -> /video/.
# The comment asserted "AUD cards live under the DVIDS /audio/ path" and
# nothing ever checked it. Probed 2026-08-08 against DVIDS:
#
#   /audio/1006119        -> 404      /video/1006119        -> 200
#   /audio/embed/1006119  -> 404      /video/embed/1006119  -> 200
#   (same for 1007870, 1010337, 1014110)
#
# DVIDS serves these assets as mp4 under /video/ regardless of how the
# government catalogues them -- an "audio" release is an mp4 carrying a
# static image. So all 15 AUD cards carried a dead asset_url, and the
# site's "Open on DVIDS" link 404'd on every one.
#
# asset_type itself is NOT touched: it mirrors the government's own
# categorisation and must keep doing so. Only OUR derived URL changes.


def _card(card_id: str, asset_type: str, dvids_id: str = "1006119"):
    from types import SimpleNamespace

    return SimpleNamespace(
        card_id=card_id, asset_type=asset_type, dvids_video_id=dvids_id
    )


def _entry(asset_type: str, tmp_path: Path) -> dict:
    local = tmp_path / "1006119.mp4"
    local.write_bytes(b"mp4")
    return helpers.build_registry_entry(
        card=_card("167f6a21c7238d0c", asset_type),
        local_path=local,
        sha="a" * 64,
        size=3,
        archive_key="archive/" + "a" * 64 + ".mp4",
        current_key="167f6a21c7238d0c.mp4",
        source_label="test",
    )


def test_aud_card_registers_the_live_dvids_video_url(tmp_path: Path):
    assert _entry("AUD", tmp_path)["asset_url"] == (
        "https://www.dvidshub.net/video/1006119"
    )


def test_vid_card_unchanged(tmp_path: Path):
    assert _entry("VID", tmp_path)["asset_url"] == (
        "https://www.dvidshub.net/video/1006119"
    )


def test_aud_and_vid_agree_so_one_card_cannot_hold_two_urls(tmp_path: Path):
    """The registry URL-stability invariant broke because the same bytes were
    registered under /video/ (2026-05) then /audio/ (2026-07)."""
    assert _entry("AUD", tmp_path)["asset_url"] == _entry("VID", tmp_path)["asset_url"]
