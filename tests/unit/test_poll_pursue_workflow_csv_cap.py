"""The poll workflow verifies CSV bytes (size cap + sha) before committing."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "poll-pursue.yml"


def _run(name_part: str) -> str:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["poll"]["steps"]
    matches = [s for s in steps if name_part in str(s.get("name", ""))]
    assert len(matches) == 1
    return matches[0]["run"]


@pytest.mark.parametrize("name", ["Commit new sha", "Archive CSV bytes on every poll"])
def test_csv_commit_steps_verify_bytes_first(name: str) -> None:
    run = _run(name)
    verify = run.find("scripts/verify_csv_artifact.py")
    assert verify >= 0, "step must call the verifier"
    assert verify < run.find('git add "data/raw/csv'), "verify before staging"
    assert "data/raw/csv/*.csv" not in run, "stage only the verified sha file"
