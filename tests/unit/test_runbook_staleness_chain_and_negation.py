"""The staleness gate's two runbook rules, run through ``_check_file``."""

from pathlib import Path

from scripts.runbook_staleness_check import _check_file

_PUSH = "git push origin main"
_RUN = "curate clean-qc run --cards <ids>"
_PUB = "curate publish clean-qc --version <N>"


def _hits(tmp_path: Path, body: str) -> list[tuple[int, str, str]]:
    fixture = tmp_path / "ship-tranche.md"
    fixture.write_text(body)
    return _check_file(fixture)


def _chain_hits(tmp_path: Path, body: str) -> list[tuple[int, str, str]]:
    return [h for h in _hits(tmp_path, body) if "clean-qc" in h[1]]


def test_a_distant_negation_word_does_not_forgive_a_code_span(tmp_path: Path) -> None:
    assert len(_hits(tmp_path, f"Never mind, now run `{_PUSH}`.\n")) == 1


def test_a_directly_negated_code_span_is_still_forgiven(tmp_path: Path) -> None:
    assert _hits(tmp_path, f"Merge the PR (do NOT use `{_PUSH}`).\n") == []


def test_publish_far_from_its_run_is_flagged(tmp_path: Path) -> None:
    body = f"{_RUN}\n\ntext\n\nmore text\n\nstill more\n\n{_PUB}\n"
    assert len(_chain_hits(tmp_path, body)) == 1


def test_publish_with_no_run_before_it_is_flagged(tmp_path: Path) -> None:
    assert len(_chain_hits(tmp_path, f"```\n{_PUB}\n```\n")) == 1


def test_run_joined_to_publish_by_and_is_clean(tmp_path: Path) -> None:
    assert _chain_hits(tmp_path, f"{_RUN} && {_PUB}\n") == []


def test_run_joined_to_publish_across_a_continuation_is_clean(tmp_path: Path) -> None:
    assert _chain_hits(tmp_path, f"{_RUN} && \\\n  {_PUB}\n") == []
    assert _chain_hits(tmp_path, f"{_RUN} &&\n{_PUB}\n") == []


def test_a_semicolon_or_newline_between_them_is_flagged(tmp_path: Path) -> None:
    assert len(_chain_hits(tmp_path, f"{_RUN}; {_PUB}\n")) == 1
    assert len(_chain_hits(tmp_path, f"{_RUN}\n{_PUB}\n")) == 1


def test_a_run_with_no_publish_is_clean(tmp_path: Path) -> None:
    assert _chain_hits(tmp_path, f"{_RUN}\n") == []
