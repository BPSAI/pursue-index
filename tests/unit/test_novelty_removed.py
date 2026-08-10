"""The novelty-detection surface has been removed as ordinary product
evolution: the reference corpus was a static synthetic placeholder for a
design that was not carried forward, never a real coverage measurement.

This is a regression guard, not a feature test. It asserts that the whole
surface stays gone — the backend pipeline, its builders, its source data, the
served payload, and the reader-facing panels and filter that presented the
comparison. A panel with no payload behind it is a promise the site cannot
keep, so the frontend is covered here alongside the backend rather than left
to drift back in.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
runner = CliRunner()


def test_novelty_package_is_gone():
    assert not (REPO_ROOT / "src" / "pursue_index" / "novelty").exists()


def test_novelty_builder_scripts_are_gone():
    assert not (REPO_ROOT / "scripts" / "build_novelty_data.py").exists()
    assert not (REPO_ROOT / "scripts" / "build_synthetic_reference.py").exists()


def test_synthetic_reference_and_sidecar_data_are_gone():
    assert not (REPO_ROOT / "data" / "reference").exists()
    assert not (REPO_ROOT / "data" / "novelty").exists()


def test_served_payload_is_gone():
    assert not (REPO_ROOT / "web" / "public" / "data" / "novelty.json").exists()


def test_reader_facing_surfaces_are_gone():
    """No panel, filter or type describing a comparison the site cannot make."""
    components = REPO_ROOT / "web" / "src" / "components"
    assert not (components / "CardProvenance.tsx").exists()
    assert not (components / "NoveltyFilter.ts").exists()
    for path in (
        components / "CardExplorer.tsx",
        REPO_ROOT / "web" / "src" / "data" / "types.ts",
        REPO_ROOT / "web" / "src" / "pages" / "card" / "[card_id].astro",
    ):
        assert "novelty" not in path.read_text(encoding="utf-8").lower(), path
        assert "disclosure" not in path.read_text(encoding="utf-8").lower(), path


def test_cli_has_no_novelty_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "novelty" not in result.output.lower()


def test_rebuild_derivatives_does_not_reference_novelty():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "novelty" not in makefile.lower()
