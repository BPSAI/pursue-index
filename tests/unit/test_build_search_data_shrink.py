"""``scripts/build_search_data.py`` refuses to shrink the committed pages.json."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_search_data.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_search_data", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest(path: Path, cards: dict[str, str]) -> Path:
    """``cards`` maps card_id -> asset_type."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cards": [
                    {"card_id": cid, "title": f"T {cid}", "asset_type": kind}
                    for cid, kind in cards.items()
                ]
            }
        )
    )
    return path


def _ocr(ocr_dir: Path, card_id: str) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    (card_dir / "pages.jsonl").write_text(
        json.dumps({"page": 1, "text": f"text {card_id}"}) + "\n"
    )


def _committed(out: Path, ids: list[str]) -> None:
    out.write_text(
        json.dumps([{"card_id": i, "page": 1, "text": "old"} for i in ids])
    )


def _run(tmp_path: Path, mod, **kw):  # type: ignore[no-untyped-def]
    return mod.build(
        ocr_dir=tmp_path / "ocr",
        manifest_path=tmp_path / "manifest.json",
        out_path=tmp_path / "pages.json",
        audit_log=tmp_path / "audit-log.jsonl",
        **kw,
    )


def test_shrinking_root_exits_1_naming_missing_cards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _manifest(tmp_path / "manifest.json", {"c1": "PDF", "c2": "PDF", "c3": "PDF"})
    _ocr(tmp_path / "ocr", "c1")
    _committed(tmp_path / "pages.json", ["c1", "c2", "c3"])

    rc = _run(tmp_path, _load())

    assert rc == 1
    err = capsys.readouterr().err
    assert "c2" in err and "c3" in err
    # The refusal leaves the committed payload untouched.
    assert {d["card_id"] for d in json.loads((tmp_path / "pages.json").read_text())} == {
        "c1", "c2", "c3",
    }
    assert not (tmp_path / "audit-log.jsonl").exists()


def test_allow_shrink_with_reason_exits_0_and_audits(tmp_path: Path) -> None:
    _manifest(tmp_path / "manifest.json", {"c1": "PDF", "c2": "PDF", "c3": "PDF"})
    _ocr(tmp_path / "ocr", "c1")
    _committed(tmp_path / "pages.json", ["c1", "c2", "c3"])

    rc = _run(tmp_path, _load(), allow_shrink_reason="x")

    assert rc == 0
    (row,) = [
        json.loads(line)
        for line in (tmp_path / "audit-log.jsonl").read_text().splitlines()
    ]
    assert row["reason"] == "x"
    assert row["shrunk"] == ["c2", "c3"]
    assert row["script"] == "build_search_data.py"
    assert {d["card_id"] for d in json.loads((tmp_path / "pages.json").read_text())} == {"c1"}


def test_manifest_card_without_ocr_or_transcript_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No committed baseline at all: only the manifest-coverage rule fires."""
    _manifest(tmp_path / "manifest.json", {"c1": "PDF", "orphan": "PDF"})
    _ocr(tmp_path / "ocr", "c1")

    rc = _run(tmp_path, _load())

    assert rc == 1
    assert "orphan" in capsys.readouterr().err
    assert not (tmp_path / "pages.json").exists()


def test_transcript_only_card_counts_as_covered(tmp_path: Path) -> None:
    _manifest(tmp_path / "manifest.json", {"c1": "PDF", "aud": "AUD"})
    _ocr(tmp_path / "ocr", "c1")
    _ocr(tmp_path / "ocr", "aud")
    (tmp_path / "ocr" / "aud" / "meta.json").write_text(
        json.dumps({"status": "ok", "engine": "assemblyai"})
    )
    _committed(tmp_path / "pages.json", ["c1", "aud"])

    assert _run(tmp_path, _load()) == 0


def test_uncovered_non_pdf_cards_do_not_block(tmp_path: Path) -> None:
    """Un-transcribed VID/AUD cards are a backlog, not a shrink."""
    _manifest(
        tmp_path / "manifest.json", {"c1": "PDF", "vid": "VID", "aud": "AUD"}
    )
    _ocr(tmp_path / "ocr", "c1")
    _committed(tmp_path / "pages.json", ["c1"])

    assert _run(tmp_path, _load()) == 0


def test_growth_is_not_a_shrink(tmp_path: Path) -> None:
    _manifest(tmp_path / "manifest.json", {"c1": "PDF", "c2": "PDF"})
    _ocr(tmp_path / "ocr", "c1")
    _ocr(tmp_path / "ocr", "c2")
    _committed(tmp_path / "pages.json", ["c1"])

    assert _run(tmp_path, _load()) == 0
    assert not (tmp_path / "audit-log.jsonl").exists()


def test_cli_allow_shrink_requires_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load()
    monkeypatch.setattr("sys.argv", ["build_search_data.py", "--allow-shrink"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2


def test_unreadable_ocr_root_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _manifest(tmp_path / "manifest.json", {})
    (tmp_path / "ocr").write_text("not a directory")

    assert _run(tmp_path, _load()) == 1
    assert "cannot read" in capsys.readouterr().err
