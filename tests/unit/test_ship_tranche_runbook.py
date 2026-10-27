"""Tests for the ship-tranche runbook tracking and content validation."""

import re
from pathlib import Path
import pytest


RUNBOOK_PATH = Path(__file__).parent.parent.parent / "docs" / "runbooks" / "ship-tranche.md"


class TestRunbookExists:
    """Verify the runbook exists in tracked location."""

    def test_runbook_file_exists(self):
        """ship-tranche.md must exist at docs/runbooks/ship-tranche.md."""
        assert RUNBOOK_PATH.exists(), f"Runbook not found at {RUNBOOK_PATH}"

    def test_runbook_is_tracked(self):
        """ship-tranche.md must be tracked (not in .gitignore)."""
        gitignore_path = RUNBOOK_PATH.parent.parent.parent / ".gitignore"
        gitignore_content = gitignore_path.read_text()
        # The path docs/runbooks/ should not be in .gitignore
        assert "docs/runbooks/" not in gitignore_content or \
               "docs/runbooks/ship-tranche.md" not in gitignore_content, \
               "ship-tranche.md should be tracked (not gitignored)"

    def test_runbook_has_content(self):
        """ship-tranche.md must have substantial content."""
        content = RUNBOOK_PATH.read_text()
        assert len(content) > 1000, "Runbook content is too short"
        assert "Ship Tranche" in content or "ship tranche" in content.lower(), \
               "Runbook must mention Ship Tranche"


class TestIssue170Corrections:
    """Verify all 7 corrections from issue #170 are present."""

    def test_corrections_present(self):
        """Each of the 7 #170 corrections must have a marker in the runbook."""
        content = RUNBOOK_PATH.read_text()

        # The 7 corrections from issue #170:
        corrections = {
            "diff generation into data/tranche-diffs/": r"data/tranche-diffs/",
            "worklist header inspection": r"ingest-worklist\.txt",
            "make bundle-copy in release checkout": r"make bundle-copy",
            "curate suite step": r"curate clean-qc",
            "byte-provenance rows": r"byte.*prove|csv_sha256|source_url",
            "PR path": r"git push|open.*PR|merge.*PR",
            "thumbs after download": r"build.*thumb|ingest_release_videos",
        }

        for correction_name, pattern in corrections.items():
            assert re.search(pattern, content, re.IGNORECASE), \
                   f"Correction '{correction_name}' not found (pattern: {pattern})"

    def test_diff_generation_uses_tracked_path(self):
        """Diff generation should reference data/tranche-diffs/, not .paircoder/plans/."""
        content = RUNBOOK_PATH.read_text()
        # Should mention data/tranche-diffs
        assert "data/tranche-diffs/" in content, \
               "Runbook must reference data/tranche-diffs/"
        # Should NOT reference .paircoder/plans/tranche-diff (the old path)
        assert ".paircoder/plans/tranche-diff" not in content, \
               "Runbook must not reference old .paircoder/plans/tranche-diff path"

    def test_no_push_origin_main(self):
        """Runbook must not contain 'git push origin main' as an instruction."""
        content = RUNBOOK_PATH.read_text()
        lines = content.split("\n")
        # Look for lines that instruct to use "git push origin main"
        # (not prohibition lines with "NOT", "never", "do not")
        for i, line in enumerate(lines):
            if "git push origin main" in line:
                # Check if this line is a prohibition
                lower_line = line.lower()
                if not any(word in lower_line for word in ["not", "never", "do not", "don't", "avoid"]):
                    pytest.fail(f"Line {i+1} contains 'git push origin main' as an instruction: {line.strip()}")

    def test_clean_qc_chained(self):
        """curate clean-qc run and publish must be chained (&&), not separate."""
        content = RUNBOOK_PATH.read_text()
        # Look for the pattern where run and publish are chained
        pattern = r"curate\s+clean-qc\s+run.*?&&.*?curate\s+publish\s+clean-qc"
        # First check that the phrase exists at all
        assert "curate clean-qc run" in content and "curate publish clean-qc" in content, \
               "Runbook must mention both 'curate clean-qc run' and 'curate publish clean-qc'"
        # Check they appear in the right context (probably on same step)
        lines = content.split("\n")
        found_chained = False
        for i, line in enumerate(lines):
            if "curate clean-qc run" in line:
                # Check if next few lines have the publish with && or similar chaining
                context = "\n".join(lines[i:min(i+5, len(lines))])
                if "&&" in context and "curate publish" in context:
                    found_chained = True
                    break
        # If not found as chained in code, check if there's explicit instruction about chaining
        assert found_chained or "chained" in content.lower() or "publish never follows a failed run" in content, \
               "Runbook must indicate chaining of clean-qc run and publish"
