"""The shrink guard must not fire on the committed tree.

Builds ``pages.json`` and ``embed_index.json`` from a data root MOCKED as
complete for the committed payload — every card the committed ``pages.json``
carries has OCR pages, every committed embed row has a vector — against the
real manifest, committed payloads and image-observation sidecars. A guard that
also flagged legitimately text-less cards (un-transcribed AUD, VID) would fail
``make rebuild-derivatives`` on a tree that is fine.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "web" / "public" / "data"
MANIFEST = REPO_ROOT / "data" / "manifests" / "latest.json"


def _script(name: str):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_complete_ocr_root(root: Path, pages: list[dict]) -> Path:
    """One ``ocr/<card_id>/{meta.json,pages.jsonl}`` per committed card."""
    ocr = root / "ocr"
    by_card: dict[str, list[dict]] = {}
    for d in pages:
        by_card.setdefault(d["card_id"], []).append(d)
    for card_id, rows in by_card.items():
        card_dir = ocr / card_id
        card_dir.mkdir(parents=True)
        (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
        with (card_dir / "pages.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps({"page": r["page"], "text": r["text"] or " "}) + "\n")
    return ocr


def _mock_embeddings(root: Path, embed_index: dict) -> Path:
    """A store holding one 2-dim vector per committed embed row."""
    dim, rows = 2, embed_index["pages"]
    in_dir = root / "embeddings" / "voyage-3"
    in_dir.mkdir(parents=True)
    flat = [0.25] * (len(rows) * dim)
    (in_dir / "vectors.bin").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    (in_dir / "index.json").write_text(
        json.dumps(
            {
                "model_id": "voyage-3",
                "dim": dim,
                "n": len(rows),
                "pages": [
                    {"card_id": c, "page": p, "text_sha": "x", "offset": i * dim * 4}
                    for i, (c, p) in enumerate(rows)
                ],
            }
        )
    )
    return root / "embeddings"


@pytest.fixture()
def committed_tree(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    shutil.copy(DATA / "pages.json", out / "pages.json")
    shutil.copy(DATA / "embed_index.json", out / "embed_index.json")
    return out


def test_search_build_passes_on_committed_tree(tmp_path: Path, committed_tree: Path) -> None:
    pages = json.loads((DATA / "pages.json").read_text())
    ocr = _mock_complete_ocr_root(tmp_path / "root", pages)

    rc = _script("build_search_data").build(
        ocr_dir=ocr,
        manifest_path=MANIFEST,
        out_path=committed_tree / "pages.json",
        image_obs_index=REPO_ROOT / "web" / "src" / "data" / "image-observations" / "index.json",
        audit_log=tmp_path / "audit-log.jsonl",
    )

    assert rc == 0
    assert not (tmp_path / "audit-log.jsonl").exists()


def test_embed_build_passes_on_committed_tree(tmp_path: Path, committed_tree: Path) -> None:
    pages = json.loads((DATA / "pages.json").read_text())
    embed_index = json.loads((DATA / "embed_index.json").read_text())
    ocr = _mock_complete_ocr_root(tmp_path / "root", pages)
    store = _mock_embeddings(tmp_path / "root", embed_index)

    rc = _script("build_embed_data").build(
        embeddings_root=store,
        model_id="voyage-3",
        out_dir=committed_tree,
        manifest_path=MANIFEST,
        ocr_dir=ocr,
        audit_log=tmp_path / "audit-log.jsonl",
    )

    assert rc == 0
    assert not (tmp_path / "audit-log.jsonl").exists()


def test_make_target_propagates_guard_failure_and_shrink_args() -> None:
    """``| tail -1`` reports tail's status, so the search step must not use it."""
    plan = subprocess.run(
        ["make", "-n", "rebuild-derivatives", "SHRINK_ARGS=--allow-shrink --reason x"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    search = next(line for line in plan.splitlines() if "build_search_data.py" in line)
    embed = next(line for line in plan.splitlines() if "build_embed_data.py" in line)
    assert "|| {" in search and "build_search_data.py --allow-shrink --reason x" in search
    assert "--allow-shrink --reason x" in embed
