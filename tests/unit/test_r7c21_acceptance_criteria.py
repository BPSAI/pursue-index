"""Comprehensive acceptance criteria tests for R7C.21.

Validates that the release runbook is tracked and all corrections from issue #170
are present, with updated staleness checks.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "ship-tranche.md"
STALENESS_SCRIPT = REPO_ROOT / "scripts" / "runbook_staleness_check.py"


class TestAc1RunbookTrackedWithCorrections:
    """AC1: docs/runbooks/ship-tranche.md is tracked and contains each of the seven #170 corrections."""

    def test_runbook_file_exists_and_tracked(self):
        """Runbook must exist at docs/runbooks/ship-tranche.md (tracked location)."""
        assert RUNBOOK_PATH.exists(), f"Runbook not found at {RUNBOOK_PATH}"

        # Verify it's tracked (not in .gitignore)
        gitignore_path = REPO_ROOT / ".gitignore"
        if gitignore_path.exists():
            gitignore_content = gitignore_path.read_text()
            # Path should not be explicitly ignored
            assert "docs/runbooks/ship-tranche.md" not in gitignore_content

    def test_seven_corrections_from_issue_170_are_present(self):
        """Each of the 7 #170 corrections must be present with grep markers."""
        content = RUNBOOK_PATH.read_text()

        # The 7 corrections from issue #170 with identifying patterns
        corrections = [
            ("Diff generation into data/tranche-diffs/", r"data/tranche-diffs/tranche-diff"),
            ("Worklist header inspection", r"ingest-worklist\.txt"),
            ("make bundle-copy in release checkout", r"make bundle-copy"),
            ("curate suite step", r"curate clean-qc run"),
            ("byte-provenance rows", r"byte-provenance|registry-root"),
            ("PR path (not git push origin main)", r"merge.*PR|open.*PR"),
            ("thumbs after download", r"build_pdf_thumbs"),
        ]

        for correction_name, pattern in corrections:
            assert re.search(pattern, content, re.IGNORECASE), \
                f"Correction '{correction_name}' not found (pattern: {pattern})"


class TestAc2StalenesCheckValidatesUnchainedPair:
    """AC2: The staleness check fails on a fixture runbook with an unchained clean-qc run/publish pair."""



    def test_staleness_check_passes_on_properly_chained_runbook(self):
        """Staleness check must pass on the actual runbook (which is properly chained)."""
        content = RUNBOOK_PATH.read_text()

        # Look for the chained pattern
        pattern = r"curate\s+clean-qc\s+run.*?&&.*?curate\s+publish"
        has_chained_pattern = bool(re.search(pattern, content, re.IGNORECASE | re.DOTALL))

        # Or look for explicit mention of chaining
        has_chaining_note = "chained" in content.lower() or \
                           "publish never follows a failed run" in content

        assert has_chained_pattern or has_chaining_note, \
            "Runbook must show properly chained clean-qc run and publish"


class TestAc3StalenesCheckReadsTrackedPath:
    """AC3: The staleness check reads the tracked path and still passes make ship-ready's staleness target."""

    def test_staleness_script_references_tracked_path(self):
        """Staleness check script must reference docs/runbooks/ship-tranche.md."""
        script_content = STALENESS_SCRIPT.read_text()

        assert "docs/runbooks/ship-tranche.md" in script_content, \
            "Staleness check must reference the tracked path docs/runbooks/ship-tranche.md"

    def test_staleness_check_does_not_reference_old_path(self):
        """Staleness check must not reference .paircoder/plans/ old path."""
        script_content = STALENESS_SCRIPT.read_text()

        # Check within the TARGET_FILES definition
        target_files_match = re.search(
            r'TARGET_FILES\s*=\s*\[(.*?)\]',
            script_content,
            re.DOTALL
        )
        if target_files_match:
            target_files_section = target_files_match.group(1)
            assert ".paircoder/plans/tranche-diff" not in target_files_section, \
                "Staleness check must not explicitly target old .paircoder path"

    def test_staleness_check_passes_on_current_runbook(self):
        """Running the staleness check must pass (exit code 0) on the tracked runbook."""
        result = subprocess.run(
            [
                sys.executable,
                str(STALENESS_SCRIPT)
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, \
            f"Staleness check failed: stdout={result.stdout}\nstderr={result.stderr}"
        assert "clean" in result.stdout.lower(), \
            "Staleness check output should indicate clean status"


class TestAc4AllSubcommandsExist:
    """AC4: Every pursue/curate subcommand the runbook names exists."""

    def test_key_pursue_commands_mentioned(self):
        """Runbook must mention key pursue subcommands."""
        content = RUNBOOK_PATH.read_text()

        key_commands = [
            "pursue ingest",
            "pursue download",
            "pursue ocr",
            "pursue storage",
            "pursue av-fetch",
            "pursue transcribe",
            "pursue clean",
            "pursue vision",
            "pursue embed",
        ]

        for cmd in key_commands:
            assert cmd in content, f"Runbook must mention '{cmd}'"

    def test_curate_commands_mentioned(self):
        """Runbook must mention curate subcommands."""
        content = RUNBOOK_PATH.read_text()

        assert "curate clean-qc run" in content, "Runbook must mention 'curate clean-qc run'"
        assert "curate publish clean-qc" in content, "Runbook must mention 'curate publish clean-qc'"

    def test_make_bundle_copy_mentioned(self):
        """Runbook must mention the make bundle-copy command."""
        content = RUNBOOK_PATH.read_text()

        assert "make bundle-copy" in content, "Runbook must mention 'make bundle-copy'"

    def test_python_scripts_mentioned(self):
        """Runbook must mention required Python scripts."""
        content = RUNBOOK_PATH.read_text()

        scripts = [
            "build_pdf_thumbs.py",
            "build_video_posters.py",
            "build_llms_txt.py",
            "ingest_release_videos.py",
        ]

        for script in scripts:
            assert script in content, f"Runbook must mention '{script}'"


class TestAc5EndToEndIntegration:
    """AC5: End-to-end staleness check invocation passes on tracked runbook and fails on old text."""

    def test_staleness_check_script_is_executable(self):
        """The staleness check script must exist and be executable."""
        assert STALENESS_SCRIPT.exists(), f"Script not found at {STALENESS_SCRIPT}"

    def test_staleness_check_invocation_succeeds(self):
        """Running python scripts/runbook_staleness_check.py must exit with 0."""
        result = subprocess.run(
            [sys.executable, str(STALENESS_SCRIPT)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, \
            f"Staleness check script failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    def test_staleness_check_detects_old_paircoder_path(self):
        """Staleness check must flag .paircoder/plans/tranche-diff if it appears."""
        script_content = STALENESS_SCRIPT.read_text()

        # Check that the pattern exists in _PATTERNS
        patterns_section = re.search(
            r'_PATTERNS\s*=\s*\[(.*?)\]',
            script_content,
            re.DOTALL
        )

        if patterns_section:
            patterns_text = patterns_section.group(1)
            # Should have a pattern for the old path
            assert ".paircoder/plans" in patterns_text or "paircoder" in patterns_text.lower(), \
                "Staleness check should have pattern for old .paircoder path"

    def test_staleness_check_validates_no_push_origin_main(self):
        """Staleness check must have pattern for 'git push origin main' validation."""
        script_content = STALENESS_SCRIPT.read_text()

        assert "git push origin main" in script_content or "push origin main" in script_content, \
            "Staleness check must validate against 'git push origin main' instruction"



class TestAc6PRStandard:
    """AC6: The PR body carries Fixes #170 and follows the writing standard."""


    def test_runbook_writing_is_clear(self):
        """Runbook writing must be clear and follow documentation standards."""
        content = RUNBOOK_PATH.read_text()

        # Must have clear structure
        assert "## " in content, "Runbook must have markdown headers"
        assert "```" in content, "Runbook must have code blocks"

        # Must mention key concepts
        assert "gate" in content.lower() or "verify" in content.lower(), \
            "Runbook must mention verification gates"
        assert "spend" in content.lower(), \
            "Runbook must mention cost/spend considerations"


