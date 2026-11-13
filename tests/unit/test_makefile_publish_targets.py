"""The split release targets: publish-derivatives and publish-checks.

The data builders moved to the build repository; this repo keeps its own
generators and every gate. These tests pin that no builder from ship-ready
fell out of the release in the split, and that the stamp is verified last
and required.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Builders that now run from the build repository's build-into (step 1).
MOVED = {
    "build_search_data.py", "build_pages_cleaned.py", "build_photo_card_index.py",
    "build_video_card_index.py", "build_qc_coverage.py", "build_embed_data.py",
    "build_video_posters.py", "build_atlas_layout.py",
}


def _dry(target: str) -> str:
    out = subprocess.run(["make", "-C", str(ROOT), "-n", target, "PYTHON=python3"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _scripts(text: str) -> list[str]:
    return re.findall(r"scripts/([a-z_]+\.(?:py|mjs))", text)


def test_every_ship_ready_builder_is_either_here_or_moved() -> None:
    ship = set(_scripts(_dry("rebuild-derivatives")))
    here = set(_scripts(_dry("publish-derivatives")))
    assert ship - here - MOVED == set(), "builder dropped from the split release"
    assert not (here & MOVED), "a moved builder still runs here"


def test_publish_derivatives_runs_its_generators_in_order() -> None:
    order = _scripts(_dry("publish-derivatives"))
    assert order == [
        "build_byte_history.mjs", "build_cards_summary.mjs", "build_csv_archive.mjs",
        "build_llms_txt.py", "build_finds_og_images.py", "build_retrieve_rows.py",
        "registry_root.py", "chunk_public_assets.py",
    ]


def test_publish_checks_requires_the_stamp_last() -> None:
    text = _dry("publish-checks")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("echo")]
    stamp = [i for i, ln in enumerate(lines) if "build_stamp.py verify" in ln]
    assert stamp and "--require" in lines[stamp[-1]]
    assert all("build_stamp.py" not in ln for ln in lines[stamp[-1] + 1:])
    for gate in ("npm run build", "check_asset_budget.py", "-m pytest"):
        assert any(gate in ln for ln in lines[: stamp[-1]]), gate
