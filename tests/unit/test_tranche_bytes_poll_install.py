"""``pursue_index.tranche_bytes`` runs on the credential-free poll install.

The poll workflow installs ONLY ``requirements-poll.txt --require-hashes``
(``.github/workflows/poll-pursue.yml``). This builds a fresh venv exactly
that way -- no editable install, no project dependencies -- and runs the
byte classifier from this checkout's ``src/`` inside it, so a new import
(or a dependency that only the dev environment happens to carry) fails here
rather than on a cron tick.

Needs PyPI; skipped when PyPI is unreachable. The venv is built once per
test session.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.tranche_bytes_fakes import build_base_pdf, metadata_only_resave

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _pypi_reachable() -> bool:
    try:
        socket.create_connection(("pypi.org", 443), timeout=3).close()
    except OSError:
        return False
    return True


@pytest.fixture(scope="session")
def poll_venv_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not _pypi_reachable():
        pytest.skip("PyPI unreachable; cannot build the hash-locked poll venv")
    venv = tmp_path_factory.mktemp("poll-venv")
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "--require-hashes", "-r", str(_REPO_ROOT / "requirements-poll.txt")],
        check=True,
    )
    return python


def test_classifier_imports_and_runs_on_the_poll_install(
    poll_venv_python: Path, tmp_path: Path,
) -> None:
    base = build_base_pdf()
    (tmp_path / "old.pdf").write_bytes(base.data)
    (tmp_path / "new.pdf").write_bytes(metadata_only_resave(base))
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from pathlib import Path\n"
        "from pursue_index.tranche_bytes import classify_bytes\n"
        "print(classify_bytes(Path(sys.argv[2]), Path(sys.argv[3])))\n"
    )
    result = subprocess.run(
        [str(poll_venv_python), "-I", "-c", code, str(_REPO_ROOT / "src"),
         str(tmp_path / "old.pdf"), str(tmp_path / "new.pdf")],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "metadata-only"


def test_tranche_ready_job_imports_and_validates_on_the_poll_install(
    poll_venv_python: Path, tmp_path: Path,
) -> None:
    """R7C.31: the snapshot job's tranche-ready step -- the classifier, the
    dependency-free schema validator and the job entry point with its
    ``tranche_diff`` import closure -- runs on the hash-locked set alone, and
    the validator accepts the vendored Release-7 vector there."""
    code = (
        "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
        "import json\n"
        "from pathlib import Path\n"
        "import pursue_index.tranche_bytes\n"
        "from pursue_index.tranche_ready.schema import load_schema, validate\n"
        "import _tranche_ready_run\n"
        "vector = json.loads(Path(sys.argv[3]).read_text())\n"
        "print(len(validate(vector, load_schema())))\n"
    )
    result = subprocess.run(
        [str(poll_venv_python), "-I", "-c", code, str(_REPO_ROOT / "src"),
         str(_REPO_ROOT / "scripts"),
         str(_REPO_ROOT / "tests" / "fixtures" / "tranche-ready-096ef.json")],
        capture_output=True, text=True, cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PURSUE_REPO_ROOT": str(_REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "0"
