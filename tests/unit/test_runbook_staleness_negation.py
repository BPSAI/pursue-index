"""A stale command named inside a negation is a warning, not a stale usage."""

from pathlib import Path

from scripts.runbook_staleness_check import _check_file

_PUSH = "git push origin main"


def _hits(tmp_path: Path, body: str) -> list[tuple[int, str, str]]:
    fixture = tmp_path / "ship-tranche.md"
    fixture.write_text(body)
    return _check_file(fixture)


def test_negated_mentions_are_not_flagged(tmp_path: Path) -> None:
    body = (
        "# Runbook\n\n"
        f"1. Merge the PR (do NOT use `{_PUSH}`).\n\n"
        "padding one\n\npadding two\n\npadding three\n\n"
        f"- **Never** use `{_PUSH}` directly.\n\n"
        "padding four\n\npadding five\n\npadding six\n\n"
        f"- Open a PR instead of `{_PUSH}`.\n"
    )
    assert _hits(tmp_path, body) == []


def test_real_stale_usage_still_flagged_beside_negated_one(tmp_path: Path) -> None:
    body = (
        "# Runbook\n\n"
        f"Merge the PR (do NOT use `{_PUSH}`).\n\n"
        "padding one\n\npadding two\n\npadding three\n\n"
        f"```bash\n{_PUSH}\n```\n"
    )
    hits = _hits(tmp_path, body)
    assert len(hits) == 1
    assert hits[0][0] == 12
    assert _PUSH in hits[0][2]


def test_negation_word_on_another_line_does_not_forgive(tmp_path: Path) -> None:
    body = f"Never skip review.\n{_PUSH}\n"
    assert len(_hits(tmp_path, body)) == 1


def test_distant_earlier_negation_does_not_forgive(tmp_path: Path) -> None:
    body = f"Never mind, run {_PUSH}\n"
    assert len(_hits(tmp_path, body)) == 1


def test_code_span_with_a_negation_on_the_line_is_forgiven(tmp_path: Path) -> None:
    body = f"Do not rely on the old flow, which was `{_PUSH}`.\n"
    assert _hits(tmp_path, body) == []


def test_negation_then_few_filler_words_is_forgiven(tmp_path: Path) -> None:
    assert _hits(tmp_path, f"Never run the {_PUSH}\n") == []
