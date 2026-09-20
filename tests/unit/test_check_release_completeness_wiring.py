"""Wiring tests for ``scripts/check_release_completeness.py``: configuration
sources, the no-network guarantee, and the Makefile call site."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_release_completeness as crc  # noqa: E402

from tests.support.completeness_env import AUD, Env, registry_row  # noqa: E402


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# --- configuration ----------------------------------------------------------


def test_defaults_are_the_production_paths():
    args = crc.build_parser().parse_args([])
    assert args.manifest == _REPO_ROOT / "data" / "manifests" / "latest.json"
    assert args.waivers == _REPO_ROOT / "data" / "transcript-waivers.jsonl"
    assert args.registry == _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
    assert args.data_root is None


def test_data_root_defaults_to_pursue_data_root_env(env, capsys, monkeypatch):
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.sidecar(AUD)
    monkeypatch.setenv("PURSUE_DATA_ROOT", str(env.data_root))
    code = crc.main(
        [
            "--manifest",
            str(env.manifest),
            "--registry",
            str(env.registry),
            "--waivers",
            str(env.waivers),
        ]
    )
    assert code == 0


def test_the_committed_waivers_file_parses():
    """The shipped file may be empty but must be valid, so the real run never
    fails closed on it."""
    waivers = _REPO_ROOT / "data" / "transcript-waivers.jsonl"
    assert waivers.exists()
    crc.load_waivers(waivers)


# --- no network -------------------------------------------------------------


def test_script_imports_no_http_client():
    # Stdlib http.client is loaded transitively by the settings stack and opens
    # nothing on import; test_run_makes_no_socket_call covers actual behaviour.
    code = (
        f"import sys; sys.path.insert(0, {str(_SCRIPTS)!r}); import check_release_completeness;"
        "bad = [m for m in ('httpx', 'requests', 'aiohttp', 'urllib3')"
        " if m in sys.modules]; print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"HTTP client imported: {proc.stdout}"


def test_run_makes_no_socket_call(env, capsys, monkeypatch):
    import socket

    def _no_network(*_a, **_k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    env.set_cards({AUD: "AUD"})
    env.set_registry([registry_row(AUD)])
    env.sidecar(AUD)
    code, _ = env.run(capsys)
    assert code == 0


# --- Makefile wiring --------------------------------------------------------

_MAKEFILE = _REPO_ROOT / "Makefile"


def _ship_ready_prereqs() -> list[str]:
    for line in _MAKEFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("ship-ready:"):
            return line.split(":", 1)[1].split()
    raise AssertionError("no ship-ready target in Makefile")


def test_completeness_check_is_the_first_ship_ready_prerequisite():
    prereqs = _ship_ready_prereqs()
    assert prereqs[0] == "release-completeness"
    assert len(prereqs) > 1


def test_release_completeness_target_runs_the_script():
    text = _MAKEFILE.read_text(encoding="utf-8")
    _, _, rest = text.partition("\nrelease-completeness:")
    assert rest, "no release-completeness target"
    recipe = rest.split("\n\n", 1)[0]
    assert "scripts/check_release_completeness.py" in recipe


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_ship_ready_stops_when_the_check_exits_nonzero():
    """PYTHON=false makes the first recipe exit 1; nothing after it may run."""
    proc = subprocess.run(
        ["make", "ship-ready", "PYTHON=false"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode != 0
    assert "Rebuild derivatives" not in proc.stdout
    assert "ALL GATES PASSED" not in proc.stdout
