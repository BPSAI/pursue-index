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
