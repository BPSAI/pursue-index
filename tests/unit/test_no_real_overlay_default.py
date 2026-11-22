"""The suite never reads the repo's real ``data/date_resolutions.json``.

``tests/conftest.py`` swaps ``DEFAULT_DATE_RESOLUTIONS`` in ``poll_snapshot``
and ``tranche_diff`` for a sentinel that raises on use. These tests pin that
guard itself: a run that omits ``--date-resolutions`` trips it, an explicit
overlay does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import poll_snapshot  # noqa: E402
import tranche_diff  # noqa: E402

from tests.conftest import RealOverlayReached  # noqa: E402


@pytest.mark.parametrize("mod", [poll_snapshot, tranche_diff])
def test_default_overlay_path_is_poisoned_during_tests(mod) -> None:
    with pytest.raises(RealOverlayReached):
        mod.DEFAULT_DATE_RESOLUTIONS.exists()


def test_an_explicit_overlay_is_untouched_by_the_guard(tmp_path: Path) -> None:
    overlay = tmp_path / "date_resolutions.json"
    overlay.write_text('{"entries": []}', encoding="utf-8")
    args = poll_snapshot._build_parser().parse_args(
        ["--csv", "x.csv", "--date-resolutions", str(overlay)])
    assert args.date_resolutions == overlay and overlay.exists()
