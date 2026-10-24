"""No id taken from a tranche-diff reaches a work-list unless it is 16
lowercase hex: a tab or newline would forge extra rows or reasons."""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.card_id import InvalidCardIdError
from pursue_index.cli.ingest_from_diff import write_scoped_worklist, write_worklist_file
from pursue_index.ingest_scope import ScopedCard

_BAD = "a" * 16 + "\tnew\n" + "b" * 16


def test_scoped_worklist_refuses_an_id_that_could_forge_a_row(tmp_path: Path) -> None:
    out = tmp_path / "worklist.txt"

    with pytest.raises(InvalidCardIdError):
        write_scoped_worklist(out, [ScopedCard(_BAD, "new")], "t" * 64)

    assert not out.exists()


def test_av_worklist_refuses_an_id_that_could_forge_a_row(tmp_path: Path) -> None:
    out = tmp_path / "worklist.txt"

    with pytest.raises(InvalidCardIdError):
        write_worklist_file(out, ["c" * 16, _BAD], "t" * 64, suffix="-av")

    assert not (tmp_path / "worklist-av.txt").exists()


def test_valid_ids_are_written_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "worklist.txt"

    write_scoped_worklist(out, [ScopedCard("a" * 16, "new")], "t" * 64)

    assert f"{'a' * 16}\tnew" in out.read_text().splitlines()
