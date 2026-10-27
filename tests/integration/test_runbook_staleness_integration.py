"""Integration tests for runbook staleness check."""

import re
import subprocess
import tempfile
from pathlib import Path
import pytest


class TestRunbookStalenesIntegration:
    """Test that the staleness check works correctly with the tracked runbook."""

    def test_staleness_check_script_has_new_rules(self):
        """Verify staleness check has the new rules for #170 corrections."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "runbook_staleness_check.py"
        content = script_path.read_text()

        # Check for pattern for old path
        assert ".paircoder/plans/tranche-diff" in content, \
               "Script should check for old .paircoder/plans/tranche-diff path"

        # Check for unchained clean-qc detection logic
        assert "_check_unchained_clean_qc" in content, \
               "Script should have function to check for unchained clean-qc"

        # Check for git push origin main pattern
        patterns_section = content[content.find("_PATTERNS = ["):content.find("]", content.find("_PATTERNS = ["))]
        assert "git" in patterns_section and "push" in patterns_section and "main" in patterns_section, \
               "Script should have pattern to check for 'git push origin main'"

    def test_runbook_content_validation(self):
        """Verify the tracked runbook has all required corrections."""
        runbook_path = Path(__file__).parent.parent.parent / "docs" / "runbooks" / "ship-tranche.md"
        content = runbook_path.read_text()

        # Check for the 7 #170 corrections
        corrections = {
            "diff_path": r"data/tranche-diffs/",
            "worklist": r"ingest-worklist\.txt",
            "bundle_copy": r"make bundle-copy",
            "curate_step": r"curate clean-qc",
            "byte_provenance": r"byte.*prove|csv_sha256|source_url",
            "pr_path": r"create a PR|merge.*PR|open a PR",
            "thumbs": r"build.*thumb|ingest_release_videos",
        }

        for name, pattern in corrections.items():
            assert re.search(pattern, content, re.IGNORECASE), \
                   f"Runbook missing correction '{name}' (pattern: {pattern})"

    def test_runbook_does_not_have_old_patterns(self):
        """Verify the tracked runbook doesn't have old/deprecated patterns."""
        runbook_path = Path(__file__).parent.parent.parent / "docs" / "runbooks" / "ship-tranche.md"
        content = runbook_path.read_text()

        # Check for old patterns that should not be there
        assert ".paircoder/plans/tranche-diff" not in content, \
               "Runbook should not reference old .paircoder/plans/tranche-diff"

        # Check that git push origin main is not an instruction
        lines = content.split('\n')
        for line in lines:
            if "git push origin main" in line:
                # If it contains git push origin main, it must be a prohibition
                assert any(word in line.lower() for word in ["not", "never", "do not", "don't"]), \
                       f"Line mentions 'git push origin main' without prohibition: {line}"

    def test_tracked_runbook_exists_and_is_valid(self):
        """Verify the tracked runbook is properly created and has valid structure."""
        runbook_path = Path(__file__).parent.parent.parent / "docs" / "runbooks" / "ship-tranche.md"

        assert runbook_path.exists(), "Tracked runbook must exist"

        content = runbook_path.read_text()

        # Check for basic structure
        assert "# Ship Tranche" in content or "Ship Tranche" in content, \
               "Runbook should have a title"
        assert "## Workflow" in content, \
               "Runbook should have Workflow section"
        assert "## Gates" in content, \
               "Runbook should have Gates section"

        # Check for workflow steps
        assert "1." in content, "Runbook should have numbered steps"

        # Check for both basic and advanced commands
        assert "pursue ingest" in content
        assert "pursue ocr" in content
        assert "pursue download" in content
        assert "curate clean-qc" in content

    def test_clean_qc_is_properly_chained(self):
        """Verify clean-qc run and publish are properly chained."""
        runbook_path = Path(__file__).parent.parent.parent / "docs" / "runbooks" / "ship-tranche.md"
        content = runbook_path.read_text()

        # Find the clean-qc section
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if "curate clean-qc run" in line:
                # Check if there's a chaining indicator nearby (either && on same line or explicit instruction)
                context = '\n'.join(lines[i:min(i+3, len(lines))])
                assert "&&" in context or "chained" in context.lower(), \
                       "clean-qc run and publish must be chained"
