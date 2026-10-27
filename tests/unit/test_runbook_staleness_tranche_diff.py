"""The staleness gate keeps "generate the diff by hand" out of the runbook.

Since R7C.31 the poll's snapshot job runs the tranche diff and commits the
receipt (``data/tranche-diffs/tranche-diff-<sha12>.{json,md}``), so
``docs/runbooks/ship-tranche.md`` step 2 loads the already-computed diff.
An instruction to regenerate it -- running ``scripts/tranche_diff.py`` or
"generate the diff" -- would have the operator recompute a committed,
append-only receipt. Run through ``_check_file`` like the gate's other rules.
"""

from pathlib import Path

from scripts.runbook_staleness_check import _check_file

_LABEL = "hand-run tranche diff — the poll commits it to data/tranche-diffs/; load it"
_RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "ship-tranche.md"

_OLD_STEP_2 = (
    "2. **Generate the diff.** Compute the tranche diff into `data/tranche-diffs/`:\n"
    "   ```\n"
    "   python scripts/tranche_diff.py --new-manifest "
    "data/manifests/snapshots/\"$SHA\".json\n"
    "   ```\n"
)


def _hits(tmp_path: Path, body: str) -> list[tuple[int, str, str]]:
    fixture = tmp_path / "ship-tranche.md"
    fixture.write_text(body)
    return [h for h in _check_file(fixture) if h[1] == _LABEL]


def test_the_old_generate_the_diff_wording_is_flagged(tmp_path: Path) -> None:
    hits = _hits(tmp_path, _OLD_STEP_2)
    assert [lineno for lineno, _, _ in hits] == [1, 3]  # the heading and the command


def test_a_bare_python3_invocation_is_flagged_too(tmp_path: Path) -> None:
    assert len(_hits(tmp_path, "Run `python3 scripts/tranche_diff.py --dry-run`.\n")) == 1


def test_a_directly_negated_mention_is_allowed(tmp_path: Path) -> None:
    body = "Do NOT run `python scripts/tranche_diff.py`; the poll already committed it.\n"
    assert _hits(tmp_path, body) == []


def test_the_current_runbook_does_not_trip_the_rule() -> None:
    assert [h for h in _check_file(_RUNBOOK) if h[1] == _LABEL] == []
