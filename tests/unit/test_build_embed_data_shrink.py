"""``scripts/build_embed_data.py`` refuses to shrink the committed embed_index."""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_embed_data.py"
_DIM = 2


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("build_embed_data", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stage_store(root: Path, card_ids: list[str]) -> None:
    """An embeddings store with one page per card."""
    in_dir = root / "voyage-3"
    in_dir.mkdir(parents=True)
    flat = [0.5] * (len(card_ids) * _DIM)
    (in_dir / "vectors.bin").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    (in_dir / "index.json").write_text(
        json.dumps(
            {
                "model_id": "voyage-3",
                "dim": _DIM,
                "n": len(card_ids),
                "pages": [
                    {"card_id": cid, "page": 1, "text_sha": "x", "offset": i * _DIM * 4}
                    for i, cid in enumerate(card_ids)
                ],
            }
        )
    )


def _stage_out(out_dir: Path, page_cards: list[str], committed: list[str] | None) -> None:
    """pages.json (drives eligibility) plus an optional committed embed_index."""
    out_dir.mkdir(parents=True)
    (out_dir / "pages.json").write_text(
        json.dumps([{"card_id": c, "page": 1, "text": "readable"} for c in page_cards])
    )
    if committed is not None:
        (out_dir / "embed_index.json").write_text(
            json.dumps({"model_id": "voyage-3", "dim": _DIM, "n": len(committed),
                        "pages": [[c, 1] for c in committed]})
        )


def _ocr(ocr_dir: Path, card_id: str) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "t"}) + "\n")


def _manifest(path: Path, cards: dict[str, str]) -> Path:
    path.write_text(
        json.dumps({"cards": [{"card_id": c, "title": c, "asset_type": t}
                              for c, t in cards.items()]})
    )
    return path


def _run(tmp_path: Path, **kw):  # type: ignore[no-untyped-def]
    return _load().build(
        embeddings_root=tmp_path / "emb",
        model_id="voyage-3",
        out_dir=tmp_path / "out",
        audit_log=tmp_path / "audit-log.jsonl",
        **kw,
    )


def test_shrinking_store_exits_1_naming_missing_cards(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=["c1", "c2", "c3"])
    before = (tmp_path / "out" / "embed_index.json").read_text()

    rc = _run(tmp_path)

    assert rc == 1
    err = capsys.readouterr().err
    assert "c2" in err and "c3" in err
    assert (tmp_path / "out" / "embed_index.json").read_text() == before
    assert not (tmp_path / "out" / "embeddings.bin").exists()


def test_allow_shrink_with_reason_exits_0_and_audits(tmp_path: Path) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=["c1", "c2", "c3"])

    rc = _run(tmp_path, allow_shrink_reason="x")

    assert rc == 0
    (row,) = [json.loads(line) for line in (tmp_path / "audit-log.jsonl").read_text().splitlines()]
    assert row["script"] == "build_embed_data.py"
    assert row["shrunk"] == ["c2", "c3"]
    idx = json.loads((tmp_path / "out" / "embed_index.json").read_text())
    assert idx["pages"] == [["c1", 1]]


def test_manifest_card_without_ocr_or_transcript_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=None)
    _ocr(tmp_path / "ocr", "c1")
    manifest = _manifest(tmp_path / "manifest.json", {"c1": "PDF", "orphan": "PDF"})

    rc = _run(tmp_path, manifest_path=manifest, ocr_dir=tmp_path / "ocr")

    assert rc == 1
    assert "orphan" in capsys.readouterr().err


def test_transcript_only_card_counts_as_covered(tmp_path: Path) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=["c1"])
    _ocr(tmp_path / "ocr", "c1")
    _ocr(tmp_path / "ocr", "aud")
    manifest = _manifest(tmp_path / "manifest.json", {"c1": "PDF", "aud": "AUD"})

    assert _run(tmp_path, manifest_path=manifest, ocr_dir=tmp_path / "ocr") == 0


def test_no_committed_baseline_and_no_manifest_builds(tmp_path: Path) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=None)

    assert _run(tmp_path) == 0


def test_cli_allow_shrink_requires_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["build_embed_data.py", "--allow-shrink"])
    with pytest.raises(SystemExit) as exc:
        _load().main()
    assert exc.value.code == 2


def test_unreadable_ocr_root_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage_store(tmp_path / "emb", ["c1"])
    _stage_out(tmp_path / "out", ["c1"], committed=None)
    (tmp_path / "ocr").write_text("not a directory")
    manifest = _manifest(tmp_path / "manifest.json", {})

    assert _run(tmp_path, manifest_path=manifest, ocr_dir=tmp_path / "ocr") == 1
    assert "cannot read" in capsys.readouterr().err
