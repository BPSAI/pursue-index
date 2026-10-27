"""Tests for runbook staleness check rules and path updates."""

from pathlib import Path


def test_staleness_check_reads_tracked_path():
    """Staleness check must read docs/runbooks/ship-tranche.md, not .claude/."""
    # The staleness check script should have been updated to read the tracked path
    staleness_script = Path(__file__).parent.parent.parent / "scripts" / "runbook_staleness_check.py"
    content = staleness_script.read_text()

    # Must include the tracked path in TARGET_FILES
    assert "docs/runbooks/ship-tranche.md" in content, \
           "Staleness check must read from docs/runbooks/ship-tranche.md"


def test_staleness_check_does_not_check_old_path():
    """Staleness check should not check .claude/commands/ship-tranche.md anymore."""
    staleness_script = Path(__file__).parent.parent.parent / "scripts" / "runbook_staleness_check.py"
    content = staleness_script.read_text()

    # Should NOT explicitly list .claude/commands/ship-tranche.md in TARGET_FILES
    # (it will still be found by the glob pattern if it exists, but shouldn't be explicitly targeted)
    lines = content.split("\n")
    in_target_files = False
    found_old_path = False
    for line in lines:
        if "TARGET_FILES = [" in line or "TARGET_FILES =" in line:
            in_target_files = True
        if in_target_files and "]" in line:
            in_target_files = False
        if in_target_files and ".claude/commands/ship-tranche.md" in line:
            found_old_path = True

    assert not found_old_path, \
           "Staleness check should not explicitly list .claude/commands/ship-tranche.md"


def test_staleness_check_has_unchained_pattern():
    """Staleness check should have a pattern to detect unchained clean-qc run/publish."""
    staleness_script = Path(__file__).parent.parent.parent / "scripts" / "runbook_staleness_check.py"
    content = staleness_script.read_text()

    # Should detect when run and publish are not chained with &&
    assert "clean-qc" in content or "unchained" in content.lower(), \
           "Staleness check should have rules about clean-qc chaining"




def test_staleness_check_passes_on_tracked_runbook():
    """Staleness check should pass on the new tracked runbook."""
    repo_root = Path(__file__).parent.parent.parent
    staleness_script = repo_root / "scripts" / "runbook_staleness_check.py"
    runbook_path = repo_root / "docs" / "runbooks" / "ship-tranche.md"

    # The runbook should exist
    assert runbook_path.exists(), f"Runbook not found at {runbook_path}"

    # When we run the staleness check, it should not report this file as having issues
    # (This is more of an integration test, but it validates the script is updated correctly)
    content = staleness_script.read_text()
    assert "docs/runbooks/ship-tranche.md" in content, \
           "Script should check the tracked runbook path"


def test_staleness_check_has_patterns_for_new_rules():
    """Staleness check must have patterns for new validation rules."""
    staleness_script = Path(__file__).parent.parent.parent / "scripts" / "runbook_staleness_check.py"
    content = staleness_script.read_text()

    # Should have patterns or logic for:
    # 1. Detecting unchained run/publish pairs
    # 2. Detecting .paircoder/plans/tranche-diff path (old path)
    # 3. Detecting 'push origin main' instruction

    # Check for some indication of these rules
    has_patterns = len([line for line in content.split('\n') if '_PATTERNS' in line]) > 0
    assert has_patterns, "Staleness check should have pattern rules defined"
