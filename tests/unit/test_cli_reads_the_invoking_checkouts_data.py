"""A data command reads the checkout it is invoked from, not the one its
editable install was built against (R7C.4, acceptance criterion 1).

An editable install's ``sys.path`` entry stays pinned to whichever
checkout ran ``pip install -e .``. Before ``pursue_index.paths.repo_root()``,
every ``_REPO_ROOT``-style constant was derived from that installing
checkout's own ``__file__``, so a command run with its current directory
set to a SECOND checkout (a worktree, a fixture repo) still silently read
and wrote the first one's ``data/``. This test proves the fix with a real
subprocess -- not a monkeypatched cwd in-process -- because the bug is
specifically about what a freshly-started process resolves, which an
in-process ``CliRunner`` invocation (module already imported, ``_REPO_ROOT``
already bound) cannot exercise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SHA = "deadbeef" * 8  # 64 hex chars; present only in the second checkout's log


def _make_second_checkout(root: Path) -> None:
    """A standalone pursue-index-shaped checkout with its own approval log,
    carrying an approval this process's real checkout does not have."""
    (root / "pyproject.toml").write_text("[project]\nname = 'pursue-index'\n")
    package_dir = root / "src" / "pursue_index"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    data_dir = root / "data"
    data_dir.mkdir()
    row = {"tranche_sha256": _SHA, "approved_at": "2026-01-01T00:00:00Z", "note": "fixture"}
    (data_dir / "tranche-approval-log.jsonl").write_text(json.dumps(row) + "\n")


def test_ingest_check_reads_the_second_checkouts_approval_log(tmp_path: Path) -> None:
    second_checkout = tmp_path / "second-checkout"
    second_checkout.mkdir()
    _make_second_checkout(second_checkout)

    env = dict(os.environ)
    env.pop("PURSUE_REPO_ROOT", None)

    result = subprocess.run(
        [sys.executable, "-m", "pursue_index.cli.ingest_cli", "check", "--tranche", _SHA],
        cwd=second_checkout,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "approved" in result.stdout


def test_ingest_check_does_not_fall_back_to_the_packages_own_checkout(tmp_path: Path) -> None:
    """Sanity check for the test above: this repo's OWN approval log does
    not carry the synthetic sha, so the prior test's exit 0 really does
    prove isolation rather than a coincidence."""
    this_repo_root = Path(__file__).resolve().parents[2]
    real_log = this_repo_root / "data" / "tranche-approval-log.jsonl"
    if not real_log.is_file():
        return
    assert _SHA not in real_log.read_text()
