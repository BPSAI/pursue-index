"""``scripts/check_ship_env.py`` refuses a ship-ready run that would test the
wrong code or take a placeholder label, and ``make ship-ready`` runs it first."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_ship_env.py"
_LEAKED = ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "GNUMAKEFLAGS",
           "PURSUE_DATA_ROOT", "INTERMEDIATES_LABEL", "TAG",
           "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE")


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _LEAKED}
    env.update(extra)
    return env


def _run(*, root: Path, env: dict[str, str], module_dir: Path | None = None
         ) -> subprocess.CompletedProcess[str]:
    """Run the guard for checkout ``root``, importing pursue_index from
    ``module_dir`` (default: the real package under ``root``)."""
    args = [sys.executable, str(SCRIPT), "--root", str(root)]
    if module_dir is not None:
        env = dict(env, PYTHONPATH="")  # never inherit; set below via sitecustomize-free path
        args = [sys.executable, "-c",
                f"import sys; sys.path.insert(0, {str(module_dir)!r}); "
                f"sys.argv = {args[1:]!r}; "
                f"import runpy; runpy.run_path({str(SCRIPT)!r}, run_name='__main__')"]
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)


def _fake_pkg(tmp: Path) -> Path:
    pkg = tmp / "elsewhere" / "src"
    (pkg / "pursue_index").mkdir(parents=True)
    (pkg / "pursue_index" / "__init__.py").write_text("")
    return pkg


def test_passes_when_import_resolves_inside_this_checkout() -> None:
    out = _run(root=ROOT, env=_env(), module_dir=ROOT / "src")
    assert out.returncode == 0, out.stderr


def test_refuses_an_import_from_another_checkout(tmp_path: Path) -> None:
    other = _fake_pkg(tmp_path)
    out = _run(root=ROOT, env=_env(), module_dir=other)
    assert out.returncode == 2
    assert str(other / "pursue_index") in out.stderr
    assert str(ROOT / "src" / "pursue_index") in out.stderr
    assert "python3 -m venv" in out.stderr
    assert "pip install -e '.[dev,llm,embed,r2,og,build-tools]'" in out.stderr
    assert "make ship-ready PYTHON=" in out.stderr


def test_refuses_a_set_pythonpath() -> None:
    out = _run(root=ROOT, env=_env(PYTHONPATH="src"))
    assert out.returncode == 2
    assert "PYTHONPATH" in out.stderr
    assert "unset" in out.stderr


def test_an_empty_pythonpath_is_fine() -> None:
    out = _run(root=ROOT, env=_env(PYTHONPATH=""), module_dir=ROOT / "src")
    assert out.returncode == 0, out.stderr


def test_refuses_the_placeholder_label_by_name() -> None:
    out = _run(root=ROOT, env=_env(INTERMEDIATES_LABEL="vX.Y.Z", PURSUE_DATA_ROOT="/x"),
               module_dir=ROOT / "src")
    assert out.returncode == 2
    assert "vX.Y.Z" in out.stderr and "placeholder" in out.stderr


def test_refuses_a_label_that_is_not_a_semver_tag() -> None:
    for bad in ("1.8.1", "v1.8", "v1.8.1-rc1", "latest", "v1.8.1\n"):
        out = _run(root=ROOT, env=_env(INTERMEDIATES_LABEL=bad, PURSUE_DATA_ROOT="/x"),
                   module_dir=ROOT / "src")
        assert out.returncode == 2, bad


def test_a_real_label_needs_the_data_root() -> None:
    out = _run(root=ROOT, env=_env(INTERMEDIATES_LABEL="v1.8.1"), module_dir=ROOT / "src")
    assert out.returncode == 2
    assert "PURSUE_DATA_ROOT" in out.stderr


def test_a_real_label_with_a_data_root_passes() -> None:
    out = _run(root=ROOT, env=_env(INTERMEDIATES_LABEL="v1.8.1", PURSUE_DATA_ROOT="/x"),
               module_dir=ROOT / "src")
    assert out.returncode == 0, out.stderr


def test_ship_ready_runs_the_guard_as_its_first_step() -> None:
    env = _env(PURSUE_DATA_ROOT="/srv/pursue-data")
    out = subprocess.run(["make", "-n", "-C", str(ROOT), "ship-ready", "PYTHON=python3"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    lines = [ln for ln in out.stdout.replace("\\\n", " ").splitlines() if ln.strip() and not ln.startswith("make:")]
    assert "check_ship_env.py" in lines[0], lines[:3]


def test_the_guard_still_leads_with_a_label() -> None:
    env = _env(PURSUE_DATA_ROOT="/srv/pursue-data")
    out = subprocess.run(["make", "-n", "-C", str(ROOT), "ship-ready", "PYTHON=python3",
                          "INTERMEDIATES_LABEL=v1.2.3"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    lines = [ln for ln in out.stdout.replace("\\\n", " ").splitlines() if ln.strip() and not ln.startswith("make:")]
    assert "check_ship_env.py" in lines[0], lines[:3]


def _load_guard():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_ship_env_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _env_problems(environ: dict[str, str]) -> list[str]:
    """Only the env-variable refusals: the import check is not under test here."""
    guard = _load_guard()
    return [p for p in guard.check(ROOT, environ) if "ship-ready refuses it" in p]


def test_refuses_each_import_altering_variable_by_name() -> None:
    for var in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"):
        problems = _load_guard().check(ROOT, {var: "/somewhere"})
        head = [p for p in problems if "ship-ready refuses it" in p]
        assert len(head) == 1, (var, problems)
        assert var in head[0] and "'/somewhere'" in head[0]
        assert any(f"unset {var}" in p for p in problems), (var, problems)


def test_empty_import_altering_variables_are_fine() -> None:
    env = {v: "" for v in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE")}
    assert _env_problems(env) == []


def test_all_unset_passes_the_env_checks() -> None:
    assert _env_problems({}) == []
