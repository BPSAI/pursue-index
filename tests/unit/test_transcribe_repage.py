"""``pursue transcribe repage``: skip reporting, atomic writes, per-row page
counts, and the guard around page numbers that are citation anchors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import transcribe_cli
from pursue_index.cli.commands import app
from pursue_index.transcribe import pages as pages_mod
from pursue_index.transcribe.pages import (
    build_pages_rows,
    repaginate_sidecar,
    write_transcript_sidecar,
)

runner = CliRunner()


def _utts(n: int, first: int = 0) -> list[dict]:
    return [
        {"speaker": "A", "text": f"sentence {i}", "start": i * 1000, "end": i * 1000 + 900}
        for i in range(first, first + n)
    ]


def _write(out_dir: Path, card: str = "aud1", *, rows: tuple[tuple[str, int], ...] = (("", 6),)) -> None:
    first = 0
    for row_key, count in rows:
        write_transcript_sidecar(
            card, out_dir, _utts(count, first), row_key=row_key, multichannel=False,
            audio_duration_s=60.0, speakers=["A"], source="aud1.mp4",
        )
        first += count


def _repage(out_dir: Path, *extra: str, card: str = "aud1"):
    return runner.invoke(app, ["transcribe", "repage", "--card", card, "--out", str(out_dir), *extra])


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / "web/public/data").mkdir(parents=True)
    (root / "web/src/content/finds").mkdir(parents=True)
    (root / "web/public/data/pages.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(transcribe_cli, "_REPO_ROOT", root)
    return root


def test_repage_says_skipped_when_no_utterances_are_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(tmp_path, monkeypatch)
    card_dir = tmp_path / "ocr" / "aud1"
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"card_id": "aud1", "status": "ok"}), encoding="utf-8")

    res = _repage(tmp_path / "ocr")

    assert res.exit_code == 0, res.output
    assert "skipped (no utterances stored)" in res.output
    assert "re-paged" not in res.output


def test_repaginate_writes_pages_through_a_temp_file_and_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "ocr"
    _write(out_dir)
    calls: list[tuple[str, str]] = []
    real = pages_mod.os.replace

    def spy(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        return real(src, dst)

    monkeypatch.setattr(pages_mod.os, "replace", spy)

    repaginate_sidecar(out_dir, "aud1", char_budget=25)

    assert len(calls) == 1
    assert calls[0][1] == "pages.jsonl" and calls[0][0] != "pages.jsonl"
    assert sorted(p.name for p in (out_dir / "aud1").iterdir()) == [
        "meta.json", "pages.jsonl", "utterances.jsonl",
    ]


def test_repaginate_keeps_the_old_pages_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "ocr"
    _write(out_dir)
    before = (out_dir / "aud1" / "pages.jsonl").read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(pages_mod.os, "replace", boom)
    with pytest.raises(OSError):
        repaginate_sidecar(out_dir, "aud1", char_budget=25)

    assert (out_dir / "aud1" / "pages.jsonl").read_text(encoding="utf-8") == before


def test_repaginate_recomputes_pages_per_row(tmp_path: Path) -> None:
    out_dir = tmp_path / "ocr"
    _write(out_dir, rows=(("r1", 6), ("r2", 4)))

    assert repaginate_sidecar(out_dir, "aud1", char_budget=25) is None

    meta = json.loads((out_dir / "aud1" / "meta.json").read_text())
    expect_r1 = len(build_pages_rows(_utts(6), char_budget=25))
    expect_r2 = len(build_pages_rows(_utts(4, 6), char_budget=25))
    assert [(r["row_key"], r["pages"]) for r in meta["rows"]] == [("r1", expect_r1), ("r2", expect_r2)]
    assert meta["page_count"] == expect_r1 + expect_r2
    numbers = [json.loads(ln)["page"] for ln in (out_dir / "aud1" / "pages.jsonl").read_text().splitlines()]
    assert numbers == list(range(1, expect_r1 + expect_r2 + 1))


def test_repage_refuses_when_pages_json_already_carries_the_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "web/public/data/pages.json").write_text(
        json.dumps([{"card_id": "aud1", "page": 1, "text": "x"}]), encoding="utf-8"
    )
    out_dir = tmp_path / "ocr"
    _write(out_dir)
    before = (out_dir / "aud1" / "pages.jsonl").read_text(encoding="utf-8")

    res = _repage(out_dir)

    assert res.exit_code == 2
    assert "pages.json" in res.output and "--force" in res.output
    assert (out_dir / "aud1" / "pages.jsonl").read_text(encoding="utf-8") == before


def test_repage_refuses_when_a_find_cites_the_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "web/src/content/finds/story.mdx").write_text(
        'A quote. <Cite card="aud1" page={3} q="a quote" />\n', encoding="utf-8"
    )
    out_dir = tmp_path / "ocr"
    _write(out_dir)

    res = _repage(out_dir)

    assert res.exit_code == 2
    assert "story.mdx" in res.output


def test_repage_force_overrides_the_citation_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "web/src/content/finds/story.mdx").write_text('<Cite card="aud1" page={3} q="q" />', encoding="utf-8")
    out_dir = tmp_path / "ocr"
    _write(out_dir)

    res = _repage(out_dir, "--force")

    assert res.exit_code == 0, res.output
    assert "re-paged aud1" in res.output


def test_repage_proceeds_for_a_card_nothing_cites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path, monkeypatch)
    (root / "web/src/content/finds/story.mdx").write_text('<Cite card="other" page={3} q="q" />', encoding="utf-8")
    out_dir = tmp_path / "ocr"
    _write(out_dir)

    assert _repage(out_dir).exit_code == 0
