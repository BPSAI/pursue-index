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
