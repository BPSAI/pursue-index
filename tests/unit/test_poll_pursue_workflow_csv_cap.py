"""The poll workflow verifies CSV bytes (size cap + sha) before committing.

Both CSV-writing steps stage only a verified ``data/raw/csv/<sha>.csv``: the
sha commit stages it on ``poll/<sha12>``, the observation step copies it into
the ``poll/observations`` worktree and stages it there, and only inside the
branch where the verifier passed. The stale path records a note and never
stages bytes; it hands ``data/raw/csv`` to the note script as a read-only
input (for the file size).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "poll-pursue.yml"
_OBSERVE = "Archive CSV bytes on every poll"
# Any write of CSV bytes: a copy out of data/raw/csv, or a `git add` of it,
# in the main checkout or in a worktree (`git -C <dir> add`).
_CSV_WRITE = re.compile(r'(\bcp\s+"?data/raw/csv|\bgit\s+(?:-C\s+\S+\s+)?add\b[^\n]*data/raw/csv)')
_VERIFY = "python scripts/verify_csv_artifact.py"


def _run(name_part: str) -> str:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["poll"]["steps"]
    matches = [s for s in steps if name_part in str(s.get("name", ""))]
    assert len(matches) == 1
    return matches[0]["run"]


def _stale_and_rest(run: str) -> tuple[str, str]:
    start = run.index('"$STATUS" = "stale"')
    split = run.index("else\n", start)
    return run[start:split], run[split:]


@pytest.mark.parametrize("name", ["Commit new sha", _OBSERVE])
def test_csv_commit_steps_verify_bytes_first(name: str) -> None:
    run = _run(name)
    verify = run.find(_VERIFY)
    assert verify >= 0, "step must call the verifier"
    writes = [m.start() for m in _CSV_WRITE.finditer(run)]
    assert writes, "step must stage the verified CSV file"
    assert all(verify < w for w in writes), "verify before staging"
    assert "data/raw/csv/*.csv" not in run, "stage only the verified sha file"


def test_observation_step_writes_bytes_only_when_the_verifier_passes() -> None:
    """The copy + stage sit inside ``if <verifier>; then ... else``: a failed
    verification commits nothing."""
    _, rest = _stale_and_rest(_run(_OBSERVE))
    gate = rest.index(f"if {_VERIFY}")
    then_end = rest.index("else", gate)
    writes = [m.start() for m in _CSV_WRITE.finditer(rest)]
    assert writes and all(gate < w < then_end for w in writes)
    else_branch = rest[then_end:re.compile(r"^\s*fi\b", re.M).search(rest, then_end).start()]
    assert "not committed" in else_branch and not _CSV_WRITE.search(else_branch)


def test_stale_branch_commits_a_note_not_bytes() -> None:
    run = _run(_OBSERVE)
    stale, rest = _stale_and_rest(run)
    assert "scripts/stale_edge_note.py" in stale
    assert "verify_csv_artifact" not in stale
    assert not _CSV_WRITE.search(stale), "the stale path must not copy or stage CSV bytes"
    # data/raw/csv appears only as the note script's read-only input.
    assert stale.count("data/raw/csv") == stale.count("--csv-dir data/raw/csv") == 1
    adds = re.findall(r"\bgit\s+(?:-C\s+\S+\s+)?add\b[^\n;]*", stale)
    assert adds and all("data/stale-edge-notes" in a for a in adds)
    assert _VERIFY in rest


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


def _sandbox(tmp_path: Path, note_script: str) -> tuple[Path, Path, dict]:
    """A clone of a bare ``origin`` whose main has one commit, a fake note
    script, CSV bytes for the sha on disk, and the runner env the step reads."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "-b", "main")
    (work / "seed.txt").write_text("seed")
    _git(work, "add", "seed.txt")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    _git(work, "push", "-q", "origin", "main")
    (work / "scripts").mkdir()
    (work / "scripts" / "stale_edge_note.py").write_text(note_script)
    (work / "data" / "raw" / "csv").mkdir(parents=True)
    (work / "data" / "raw" / "csv" / f"{'a' * 64}.csv").write_text("bytes")
    (tmp_path / "runner").mkdir()
    env = {**os.environ, "SHA": "a" * 64, "STATUS": "stale", "LAST_MODIFIED": "",
           "OBS_BRANCH": "poll/observations", "RUNNER_TEMP": str(tmp_path / "runner"),
           "GITHUB_OUTPUT": str(tmp_path / "github_output")}
    return origin, work, env


def _run_step(work: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-e", "-c", _run(_OBSERVE)], cwd=work, env=env,
                          capture_output=True, text=True)


def test_stale_branch_survives_a_note_script_that_wrote_nothing(tmp_path: Path) -> None:
    """``|| true`` makes the note best-effort; the ``git add`` after it must not
    then fail on a ``data/stale-edge-notes`` that was never created."""
    origin, work, env = _sandbox(tmp_path, "import sys\nsys.exit(1)\n")
    main_before = _git(origin, "rev-parse", "main")
    result = _run_step(work, env)
    assert result.returncode == 0, result.stderr
    assert "No new CSV bytes or notes to commit." in result.stdout
    assert _git(origin, "rev-parse", "main") == main_before
    assert "poll/observations" not in _git(origin, "branch", "--list")


_WRITE_NOTE = """import pathlib, sys
args = sys.argv
notes = pathlib.Path(args[args.index("--notes-dir") + 1])
notes.mkdir(parents=True, exist_ok=True)
(notes / (args[1] + ".json")).write_text("{}")
"""


def test_stale_branch_pushes_only_the_note_to_the_observations_branch(tmp_path: Path) -> None:
    origin, work, env = _sandbox(tmp_path, _WRITE_NOTE)
    main_before = _git(origin, "rev-parse", "main")
    result = _run_step(work, env)
    assert result.returncode == 0, result.stderr
    changed = _git(origin, "diff", "--name-only", "main", "poll/observations").split()
    assert changed == [f"data/stale-edge-notes/{'a' * 64}.json"]
    assert _git(origin, "rev-parse", "main") == main_before
