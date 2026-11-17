"""The generator regenerates `## Finds` from the `.mdx`, and `--check` sees drift.

Runs `scripts/build_llms_txt.py` end to end against a throwaway data root, so
the real argument parsing, file layout and section stitching are exercised.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from pursue_index.geo.finds import load_finds, render_finds_section
from pursue_index.geo.llms import build_provenance_line

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build_llms_txt.py"

_MDX = """---
title: "A Find"
summary: "One summary line."
cards:
  - aaaaaaaaaaaaaaaa
published: 2026-07-11
---

import Cite from "../../components/Cite.astro";

## What it says

> "the original quote" <Cite card="aaaaaaaaaaaaaaaa" page={1} q="the original quote" />
"""

_PROSE = (
    "# pursue-index — full corpus\n\n"
    "Hand-written intro.\n\n"
    f"{build_provenance_line(card_count=1, csv_sha256='0' * 64)}\n\n"
    "## Methodology\n\nHand-written methodology prose.\n\n"
)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "web" / "public").mkdir(parents=True)
    (root / "data").mkdir()
    finds = root / "web" / "src" / "content" / "finds"
    finds.mkdir(parents=True)
    (finds / "a-find.mdx").write_text(_MDX, encoding="utf-8")
    manifest = {
        "csv_sha256": "0" * 64,
        "cards": [
            {
                "card_id": "aaaaaaaaaaaaaaaa",
                "title": "DOW-UAP-D001, A Card",
                "agency": "Department of War",
                "asset_type": "PDF",
            }
        ],
    }
    (root / "data" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "web" / "public" / "llms.txt").write_text(
        "# pursue-index\n\n## Cards\n\nstale\n", encoding="utf-8"
    )
    (root / "web" / "public" / "llms-full.txt").write_text(
        f"{_PROSE}## Cards\n\nstale\n\n## Finds\n\n0 stale.\n", encoding="utf-8"
    )
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PURSUE_REPO_ROOT=str(root))
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(root / "data" / "manifest.json"),
            "--ocr-dir",
            str(root / "no-ocr"),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _full(root: Path) -> str:
    return (root / "web" / "public" / "llms-full.txt").read_text(encoding="utf-8")


def test_regeneration_rebuilds_finds_and_keeps_the_prose(tmp_path):
    root = _root(tmp_path)
    assert _run(root).returncode == 0
    full = _full(root)
    assert full.startswith(_PROSE)
    assert '[cite: card aaaaaaaaaaaaaaaa p.1 "the original quote"]' in full
    assert "0 stale." not in full
    finds = load_finds(root / "web" / "src" / "content" / "finds")
    assert full.endswith("\n## Finds\n\n" + render_finds_section(finds))


def test_cards_regeneration_is_unaffected(tmp_path):
    root = _root(tmp_path)
    _run(root)
    full = _full(root)
    cards = full[full.index("## Cards\n") : full.index("## Finds\n")]
    assert "### aaaaaaaaaaaaaaaa — DOW-UAP-D001, A Card" in cards
    assert "stale" not in cards
    assert cards.endswith("\n\n")


def test_regeneration_is_idempotent(tmp_path):
    root = _root(tmp_path)
    _run(root)
    first = _full(root)
    _run(root)
    assert _full(root) == first


def test_check_fails_when_a_find_changes_until_regenerated(tmp_path):
    root = _root(tmp_path)
    _run(root)
    assert _run(root, "--check").returncode == 0

    mdx = root / "web" / "src" / "content" / "finds" / "a-find.mdx"
    mdx.write_text(_MDX.replace("the original quote", "the corrected quote"), encoding="utf-8")
    stale = _run(root, "--check")
    assert stale.returncode == 1
    assert "llms-full.txt" in stale.stdout

    _run(root)
    assert _run(root, "--check").returncode == 0
    assert "the corrected quote" in _full(root)


def test_an_unchanged_published_find_round_trips_byte_identically():
    """A real article: the committed block is exactly what its `.mdx` renders."""
    slug = "air-intelligence-study-203-1948"
    finds = [f for f in load_finds(REPO / "web" / "src" / "content" / "finds") if f.slug == slug]
    rendered = render_finds_section(finds).split("\n", 2)[2]
    published = (REPO / "web" / "public" / "llms-full.txt").read_bytes().decode("utf-8")
    start = published.index(f"\n### {slug} — ") + 1
    end = published.index("\n### ", start) + 1
    assert rendered == published[start:end].rstrip("\n") + "\n"
