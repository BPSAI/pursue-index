"""--worklist scoping for the heavy ingest executors.

A detected tranche should re-ingest only the genuinely new cards, not blindly
re-sweep the full ~222-card corpus. download/ocr are manifest-driven, so the
worklist subsets ``manifest.cards`` before fan-out; embed reads the OCR dir
directly, so the worklist card-ids are passed into ``embed_run`` as a filter.
Omitting ``--worklist`` is the full-corpus escape hatch (unchanged behavior).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.cli.worklist import (
    WorklistTrancheError,
    apply_worklist,
    read_worklist,
    require_worklist_tranche,
    worklist_card_ids,
    worklist_header_tranche,
)
from pursue_index.scrape.manifest import save_manifest
from pursue_index.scrape.types import CardMetadata, Manifest

runner = CliRunner()

_SHA = "deadbeef"


def _card(card_id: str) -> CardMetadata:
    return CardMetadata(card_id=card_id, title="t", asset_type="PDF", agency="a")


def _manifest(ids: list[str]) -> Manifest:
    return Manifest(
        source_url="https://example.com/data.csv",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        csv_sha256=_SHA,
        cards=[_card(i) for i in ids],
    )


def _write_worklist(tmp_path: Path, ids: list[str], tranche_sha: str = _SHA) -> Path:
    p = tmp_path / "worklist.txt"
    p.write_text(f"# tranche: {tranche_sha}\n" + "\n".join(ids) + "\n", encoding="utf-8")
    return p


def _write_manifest(tmp_path: Path, ids: list[str]) -> Path:
    p = tmp_path / "manifest.json"
    save_manifest(_manifest(ids), p)
    return p


# --- helper units ----------------------------------------------------------


def test_read_worklist_ignores_blanks_and_comments(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("a\n\n  # a comment\nb\n  c  \n", encoding="utf-8")
    assert read_worklist(p) == ["a", "b", "c"]


def test_read_worklist_drops_the_reason_tag(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("# tranche: deadbeef\na\tnew\nb\tbytes-changed\n", encoding="utf-8")
    assert read_worklist(p) == ["a", "b"]


def test_worklist_header_tranche_reads_the_header_line(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("# tranche: abc123\n# a comment\nid1\n", encoding="utf-8")
    assert worklist_header_tranche(p) == "abc123"


def test_worklist_header_tranche_missing_is_none(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("id1\nid2\n", encoding="utf-8")
    assert worklist_header_tranche(p) is None


def test_worklist_header_tranche_only_recognized_before_card_rows(tmp_path: Path) -> None:
    """A '# tranche: ...' line after the first non-comment row doesn't count
    -- the header must come first."""
    p = tmp_path / "wl.txt"
    p.write_text("id1\n# tranche: abc123\n", encoding="utf-8")
    assert worklist_header_tranche(p) is None


def test_require_worklist_tranche_passes_on_match(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("# tranche: abc123\nid1\n", encoding="utf-8")
    require_worklist_tranche(p, "abc123")  # no raise


def test_require_worklist_tranche_raises_naming_both_shas_on_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("# tranche: old-sha\nid1\n", encoding="utf-8")
    with pytest.raises(WorklistTrancheError) as excinfo:
        require_worklist_tranche(p, "new-sha")
    assert "old-sha" in str(excinfo.value)
    assert "new-sha" in str(excinfo.value)


def test_require_worklist_tranche_raises_on_missing_header(tmp_path: Path) -> None:
    p = tmp_path / "wl.txt"
    p.write_text("id1\nid2\n", encoding="utf-8")
    with pytest.raises(WorklistTrancheError) as excinfo:
        require_worklist_tranche(p, "new-sha")
    assert "new-sha" in str(excinfo.value)


def test_worklist_card_ids_none_is_none() -> None:
    assert worklist_card_ids(None) is None


def test_worklist_card_ids_requires_promoted_sha_when_path_given(tmp_path: Path) -> None:
    p = _write_worklist(tmp_path, ["a"])
    with pytest.raises(ValueError):
        worklist_card_ids(p)


def test_worklist_card_ids_raises_on_tranche_mismatch(tmp_path: Path) -> None:
    p = _write_worklist(tmp_path, ["a"], tranche_sha="old-sha")
    with pytest.raises(WorklistTrancheError):
        worklist_card_ids(p, promoted_sha="new-sha")


def test_apply_worklist_none_is_noop() -> None:
    m = _manifest(["a", "b"])
    assert apply_worklist(m, None) is m


def test_apply_worklist_subsets_in_manifest_order(tmp_path: Path) -> None:
    m = _manifest(["a", "b", "c", "d"])
    wl = _write_worklist(tmp_path, ["c", "a"])  # reversed order in the file
    out = apply_worklist(m, wl)
    assert [c.card_id for c in out.cards] == ["a", "c"]  # manifest order preserved
    assert out.csv_sha256 == m.csv_sha256  # other fields untouched


def test_apply_worklist_ignores_unknown_ids(tmp_path: Path) -> None:
    m = _manifest(["a", "b"])
    wl = _write_worklist(tmp_path, ["b", "zzz-not-in-manifest"])
    out = apply_worklist(m, wl)
    assert [c.card_id for c in out.cards] == ["b"]


# --- download run ----------------------------------------------------------


def test_download_run_worklist_scopes_to_listed(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    async def fake_download_all(m):
        seen["ids"] = [c.card_id for c in m.cards]
        return []

    monkeypatch.setattr("pursue_index.download.downloader.download_all", fake_download_all)
    mpath = _write_manifest(tmp_path, ["a", "b", "c"])
    wpath = _write_worklist(tmp_path, ["a", "c"])
    res = runner.invoke(app, ["download", "run", "--manifest", str(mpath), "--worklist", str(wpath)])
    assert res.exit_code == 0, res.output
    assert seen["ids"] == ["a", "c"]


def test_download_run_without_worklist_is_full_corpus(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    async def fake_download_all(m):
        seen["ids"] = [c.card_id for c in m.cards]
        return []

    monkeypatch.setattr("pursue_index.download.downloader.download_all", fake_download_all)
    mpath = _write_manifest(tmp_path, ["a", "b", "c"])
    res = runner.invoke(app, ["download", "run", "--manifest", str(mpath)])
    assert res.exit_code == 0, res.output
    assert seen["ids"] == ["a", "b", "c"]


# --- ocr run ---------------------------------------------------------------


def test_ocr_run_worklist_scopes_to_listed(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    async def fake_ocr_all(m, **kwargs):
        seen["ids"] = [c.card_id for c in m.cards]
        return None

    monkeypatch.setattr("pursue_index.ocr.pipeline.ocr_all", fake_ocr_all)
    mpath = _write_manifest(tmp_path, ["a", "b", "c"])
    wpath = _write_worklist(tmp_path, ["b"])
    res = runner.invoke(app, ["ocr", "run", "--manifest", str(mpath), "--worklist", str(wpath)])
    assert res.exit_code == 0, res.output
    assert seen["ids"] == ["b"]


# --- embed run -------------------------------------------------------------


def _stub_embed_cli(monkeypatch, seen: dict) -> None:
    monkeypatch.setattr("pursue_index.cli.embed_cli._make_embedder", lambda *a, **k: object())

    def fake_embed_run(**kwargs):
        seen["only_cards"] = kwargs.get("only_cards")
        return SimpleNamespace(embedded=0, skipped=0, total_tokens=0, cards_seen=0)

    monkeypatch.setattr("pursue_index.embed.pipeline.embed_run", fake_embed_run)


def test_embed_run_worklist_passes_only_cards(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    _stub_embed_cli(monkeypatch, seen)
    mpath = _write_manifest(tmp_path, ["a", "b", "c"])
    wpath = _write_worklist(tmp_path, ["a", "c"])
    res = runner.invoke(app, ["embed", "run", "--manifest", str(mpath), "--worklist", str(wpath)])
    assert res.exit_code == 0, res.output
    assert seen["only_cards"] == {"a", "c"}


def test_embed_run_without_worklist_only_cards_none(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    _stub_embed_cli(monkeypatch, seen)
    mpath = _write_manifest(tmp_path, ["a", "b", "c"])
    res = runner.invoke(app, ["embed", "run", "--manifest", str(mpath)])
    assert res.exit_code == 0, res.output
    assert seen["only_cards"] is None


# --- embed pipeline filter -------------------------------------------------


def test_select_new_rows_filters_by_only_cards(tmp_path, monkeypatch) -> None:
    rows = [
        SimpleNamespace(card_id="a", page=1, text_sha="sa"),
        SimpleNamespace(card_id="b", page=1, text_sha="sb"),
        SimpleNamespace(card_id="c", page=1, text_sha="sc"),
    ]
    monkeypatch.setattr("pursue_index.embed.pipeline.iter_card_pages", lambda *a, **k: list(rows))
    from pursue_index.embed.pipeline import _select_new_rows

    new_rows, all_rows, _dim = _select_new_rows(
        tmp_path / "ocr", tmp_path / "missing-index.json", None, only_cards={"a", "c"}
    )
    assert {r.card_id for r in all_rows} == {"a", "c"}
    assert {r.card_id for r in new_rows} == {"a", "c"}
