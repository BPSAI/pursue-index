"""The static bare-python check must fail on a bare `"python"` argv fixture."""

from pathlib import Path

from tests.unit.test_no_bare_python_executable import find_bare_python_violations


def test_static_check_fails_on_bare_python_fixture(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "bad_tool.py").write_text(
        "import subprocess\nsubprocess.run([\"python\", \"-c\", \"pass\"])\n"
    )
    violations = find_bare_python_violations(tmp_path)
    assert len(violations) == 1
    assert "bad_tool.py" in violations[0]


def test_static_check_passes_on_sys_executable_fixture(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "good_tool.py").write_text(
        "import subprocess, sys\nsubprocess.run([sys.executable, \"-c\", \"pass\"])\n"
    )
    assert find_bare_python_violations(tmp_path) == []


def test_static_check_passes_on_current_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    assert find_bare_python_violations(repo_root) == []
