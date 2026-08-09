"""The novelty-detection surface (T48.2) has been removed as ordinary
product evolution: the reference corpus was a static synthetic
placeholder for an abandoned design, never a real coverage measurement.

This is a regression guard, not a feature test — it asserts the backend
pipeline, its builders, its synthetic source data, and the served
payload are actually gone, and stay gone. The frontend chip UI
(`CardProvenance.tsx`, `NoveltyFilter.ts`, the `disclosure_status` types)
is explicitly salvaged for T48.3 to re-point at a future data source and
is NOT covered by this test.
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


def test_cli_has_no_novelty_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "novelty" not in result.output.lower()


def test_rebuild_derivatives_does_not_reference_novelty():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "novelty" not in makefile.lower()
