"""Test for staleness rule that detects 'git push origin main' in runbooks.

This rule prevents accidentally documenting direct pushes to main, which
bypass the PR-based release-gate CI. The correct flow is commit on the
tranche branch and open a PR to main.
"""

import tempfile
from pathlib import Path

import pytest

from scripts.runbook_staleness_check import _check_file


def test_detects_git_push_origin_main_in_runbook() -> None:
    """Test that the staleness checker flags 'git push origin main'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = Path(tmpdir) / "test_runbook.md"
        fixture.write_text(
            "# Ship Tranche\n"
            "\n"
            "1. Commit changes\n"
            "2. Push to main\n"
            "\n"
            "```bash\n"
            "git push origin main\n"
            "```\n"
        )
        hits = _check_file(fixture)
        assert len(hits) == 1
        assert hits[0][1] == "git push origin main instruction in runbook"
        assert "git push origin main" in hits[0][2]


def test_does_not_flag_git_push_on_branch() -> None:
    """git push origin feature-branch is fine; it's main we want to prevent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = Path(tmpdir) / "test_runbook.md"
        fixture.write_text(
            "# Ship Tranche\n"
            "\n"
            "1. Commit changes\n"
            "2. Push to your branch\n"
            "\n"
            "```bash\n"
            "git push origin feature-branch\n"
            "```\n"
        )
        hits = _check_file(fixture)
        assert len(hits) == 0


def test_ignores_git_push_origin_main_in_historical_context() -> None:
    """A reference to git push origin main with historical context is forgiven."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = Path(tmpdir) / "test_runbook.md"
        fixture.write_text(
            "# Historical Release Flow\n"
            "\n"
            "Previously, we used to run:\n"
            "git push origin main\n"
            "\n"
            "But that was the old flow.\n"
        )
        hits = _check_file(fixture)
        assert len(hits) == 0


def test_empty_fixture_when_no_main_instruction() -> None:
    """Fixture without the instruction produces no hits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = Path(tmpdir) / "test_runbook.md"
        fixture.write_text(
            "# Ship Tranche\n"
            "\n"
            "1. Commit on the tranche branch\n"
            "2. Open a PR to main\n"
            "3. Merge the PR\n"
        )
        hits = _check_file(fixture)
        assert len(hits) == 0
