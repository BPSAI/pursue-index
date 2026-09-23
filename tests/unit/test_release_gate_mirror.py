"""Makefile target `gate-mirror` mirrors CI's release-gate test suite.

The release-gate CI workflow (.github/workflows/release-gate.yml) runs six
specific integration tests. The local `make gate-mirror` target must run
the exact same six tests, so a local green is a CI green.

This module asserts that the Makefile has a `gate-mirror` target, that it
names all six test files, and that `ship-ready` (the operator's pre-push
gate) depends on it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The six test files that CI's release-gate runs, in .github/workflows/release-gate.yml.
# These are the same six that should appear in the local Makefile's gate-mirror target.
GATE_TEST_FILES = {
    "tests/unit/test_snapshot_mirror_coverage.py",
    "tests/unit/test_finds_citations.py",
    "tests/unit/test_finds_validator.py",
    "tests/integration/test_card_page_coverage.py",
    "tests/integration/test_alias_destinations.py",
    "tests/integration/test_derived_payload_coverage.py",
}


def test_gate_mirror_target_exists() -> None:
    """The Makefile has a `gate-mirror` target."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert ".PHONY: gate-mirror" in makefile or "gate-mirror:" in makefile


def test_gate_mirror_lists_all_six_test_files() -> None:
    """The gate-mirror target runs all six test files that CI runs."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    for test_file in GATE_TEST_FILES:
        assert test_file in makefile, f"Makefile does not mention {test_file}"


def test_ship_ready_depends_on_gate_mirror() -> None:
    """The ship-ready target depends on gate-mirror."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    # Find the ship-ready target line.
    for line in makefile.split("\n"):
        if line.startswith("ship-ready:"):
            # This line should mention gate-mirror as a prerequisite.
            assert "gate-mirror" in line, (
                "ship-ready does not depend on gate-mirror. "
                f"Found: {line}"
            )
            break
    else:
        raise AssertionError("ship-ready target not found in Makefile")


def _ship_ready_prereqs() -> list[str]:
    for line in (REPO_ROOT / "Makefile").read_text().splitlines():
        if line.startswith("ship-ready:"):
            return line.split(":", 1)[1].split()
    raise AssertionError("ship-ready target not found in Makefile")


def test_ship_ready_depends_on_test() -> None:
    """No CI job runs the unit suite, so ship-ready must."""
    assert "test" in _ship_ready_prereqs()


def test_ship_ready_prerequisite_order() -> None:
    """The unit suite runs after the build it may read, before the CI mirror."""
    assert _ship_ready_prereqs() == [
        "release-completeness",
        "rebuild-derivatives",
        "registry-root",
        "snapshot-rotate",
        "astro-build",
        "test",
        "gate-mirror",
        "arch-check",
        "staleness",
    ]


def test_test_target_uses_the_repo_interpreter() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    recipe = makefile.split("\ntest:\n", 1)[1].split("\n", 2)[0]
    assert recipe.strip() == "$(PYTHON) -m pytest"


def test_gate_mirror_no_stale_test_references() -> None:
    """No test file added to gate-mirror without updating the AC."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    # Extract the gate-mirror target content.
    in_gate_mirror = False
    gate_mirror_lines = []
    for line in makefile.split("\n"):
        if line.startswith("gate-mirror:"):
            in_gate_mirror = True
            continue
        if in_gate_mirror:
            # Stop at the next target definition or .PHONY line.
            if line.startswith(".PHONY:") or (line and not line.startswith("\t") and line.strip()):
                break
            if line.startswith("\t"):
                gate_mirror_lines.append(line)

    gate_mirror_content = "\n".join(gate_mirror_lines)
    # Count how many of the expected test files appear.
    found_tests = {test_file for test_file in GATE_TEST_FILES if test_file in gate_mirror_content}
    assert len(found_tests) == len(GATE_TEST_FILES), (
        f"gate-mirror lists {len(found_tests)} tests; expected {len(GATE_TEST_FILES)}. "
        f"Missing: {GATE_TEST_FILES - found_tests}"
    )
