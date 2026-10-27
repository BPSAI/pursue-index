"""Test that subprocess calls use sys.executable, never bare 'python' or 'python3'."""

from __future__ import annotations

import ast
import re
from pathlib import Path


def find_bare_python_violations(repo_root: Path) -> list[str]:
    """Scan tests/ and scripts/ under `repo_root` for bare python in subprocess calls."""
    violations: list[str] = []

    # Scan both tests/ and scripts/ directories
    for pattern in ["tests/**/*.py", "scripts/**/*.py"]:
        for py_file in repo_root.glob(pattern):
            if py_file.name.startswith("test_no_bare_python"):
                continue

            try:
                tree = ast.parse(py_file.read_text())
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                # Look for subprocess.run([...], ...) calls
                if isinstance(node, ast.Call):
                    # Check if it's a subprocess function call
                    func_name = None
                    if isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        func_name = node.func.id

                    if func_name not in ("run", "call", "Popen", "check_call", "check_output"):
                        continue

                    # Check the first argument (usually the command list or string)
                    if not node.args:
                        continue

                    first_arg = node.args[0]

                    # Case 1: Direct list like ["python", ...] or ["python3", ...]
                    if isinstance(first_arg, ast.List) and first_arg.elts:
                        first_elem = first_arg.elts[0]
                        if isinstance(first_elem, ast.Constant):
                            if first_elem.value in ("python", "python3"):
                                violations.append(
                                    f"{py_file}:{first_elem.lineno} "
                                    f"bare '{first_elem.value}' in subprocess call"
                                )

                    # Case 2: String like "python ..." or "python3 ..."
                    elif isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        if first_arg.value.split()[0] in ("python", "python3"):
                            violations.append(
                                f"{py_file}:{first_arg.lineno} "
                                f"bare python in string subprocess call"
                            )

    return violations


def test_no_bare_python_in_subprocess_calls() -> None:
    """Bare 'python'/'python3' fails when the venv is not first on PATH.

    Use sys.executable instead.
    """
    repo_root = Path(__file__).resolve().parents[2]
    violations = find_bare_python_violations(repo_root)
    if violations:
        msg = "Found bare 'python' or 'python3' in subprocess calls:\n"
        msg += "\n".join(violations)
        msg += "\n\nUse sys.executable instead."
        raise AssertionError(msg)
