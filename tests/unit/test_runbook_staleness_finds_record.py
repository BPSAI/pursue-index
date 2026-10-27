"""The staleness gate requires the finds step to carry the per-candidate record.

R7C.38: before any `/finds` entry is drafted, every candidate is checked against
the existing entries and the earlier digests' cross-tranche tables, and recorded
as "new entry" or "supplements `<slug>`". The runbook's finds step must say so
and name the overlap gate (R7C.37) that enforces it at build time.
"""

from pathlib import Path

from scripts.runbook_staleness_check import _check_file

_LABEL = "finds step lacks the per-candidate new/supplements record or the overlap gate"
_RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "ship-tranche.md"

_OLD_FINDS = (
    "13. **Deploy.** Merge the PR.\n"
    "14. **Finds + tag:** fan out finds reviewers over the new cards → publish\n"
    "    quote-verified, cross-linked `/finds`, then tag the release.\n"
    "15. **Record:** update the session record.\n"
)

_NEW_FINDS = (
    "14. **Finds + tag:** check every candidate against every existing `/finds`\n"
    "    entry and earlier digests' cross-tranche tables; record \"new entry\" or\n"
    "    \"supplements `<slug>`\" per candidate before drafting. The finds overlap\n"
    "    gate (`finds_validator`) enforces it at build time.\n"
    "15. **Record:** update the session record.\n"
)


def _hits(tmp_path: Path, body: str) -> list[tuple[int, str, str]]:
    fixture = tmp_path / "ship-tranche.md"
    fixture.write_text(body)
    return [h for h in _check_file(fixture) if h[1] == _LABEL]


def test_a_finds_step_without_the_record_is_flagged(tmp_path: Path) -> None:
    hits = _hits(tmp_path, _OLD_FINDS)
    assert [lineno for lineno, _, _ in hits] == [2]


def test_a_finds_step_with_record_and_gate_passes(tmp_path: Path) -> None:
    assert _hits(tmp_path, _NEW_FINDS) == []


def test_a_finds_step_naming_the_record_but_not_the_gate_is_flagged(tmp_path: Path) -> None:
    body = _NEW_FINDS.replace("The finds overlap\n    gate (`finds_validator`) enforces it at build time.\n", "\n")
    assert len(_hits(tmp_path, body)) == 1


def test_the_current_runbook_passes() -> None:
    assert [h for h in _check_file(_RUNBOOK) if h[1] == _LABEL] == []
