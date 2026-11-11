"""The autopilot has no push / pull-request / merge code path.

Two checks: the new modules contain no argv literal that would invoke
``git push``, ``git merge`` or ``gh pr ...`` and start processes only via the
runner; and a full successful run issues no such command. The operator text
in ``result.operator_next`` is prose for a human, built from f-strings, and
is deliberately not an argv.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pursue_index.cli.tranche_cli as tranche_cli
import pursue_index.tranche_autopilot as package
from pursue_index.tranche_autopilot import AutopilotConfig, ExitCode, run_autopilot
from tests.support.autopilot_fakes import SHA, FakeRunner, make_checkout, receipt

_FORBIDDEN_TOKENS = {"push", "merge", "pr"}
_PROCESS_APIS = {"system", "popen", "Popen", "run", "call", "check_call", "check_output",
                 "spawn", "execv", "execvp"}


def _modules() -> list[Path]:
    pkg = Path(package.__file__).parent
    return [*sorted(pkg.glob("*.py")), Path(tranche_cli.__file__)]


def _argv_literals(tree: ast.AST) -> list[list[str]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List | ast.Tuple):
            consts = [e.value for e in node.elts
                      if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if consts:
                out.append(consts)
    return out


def test_no_module_carries_a_publish_argv() -> None:
    offenders = []
    for path in _modules():
        for argv in _argv_literals(ast.parse(path.read_text(encoding="utf-8"))):
            if _FORBIDDEN_TOKENS & set(argv) or argv[:1] == ["gh"]:
                offenders.append((path.name, argv))
    assert offenders == []


def test_only_the_runner_starts_processes() -> None:
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                   for a in n.names}
        imports |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom)}
        if path.name == "runner.py":
            assert "subprocess" in imports
            continue
        assert not imports & {"subprocess", "os"} or path.name in ("result.py",
                                                                    "tranche_cli.py"), path
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                 and n.func.value.id in ("os", "subprocess")}
        assert not calls & _PROCESS_APIS, (path.name, calls)


def test_a_successful_run_never_publishes(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, receipt())
    runner = FakeRunner(repo)
    (tmp_path / "root").mkdir()
    out = tmp_path / "result.json"
    code = run_autopilot(AutopilotConfig(SHA, out, repo, runner,
                                         {"PURSUE_DATA_ROOT": str(tmp_path / "root")},
                                         lambda _r: 0))
    assert code == ExitCode.DONE
    for argv in runner.calls:
        assert argv[0] != "gh", argv
        assert not _FORBIDDEN_TOKENS & set(argv[:2]), argv
    git_verbs = {argv[1] for argv in runner.calls if argv[0] == "git"}
    assert git_verbs <= {"status", "symbolic-ref", "add", "commit", "rev-parse"}
    # The publish commands exist only as text for the operator.
    assert json.loads(out.read_text())["operator_next"]
