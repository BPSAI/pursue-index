"""End-to-end: the shrink guard accepts an approved rename without
``--allow-shrink``.

Runs ``scripts/build_search_data.py`` and ``scripts/build_embed_data.py`` as
real subprocesses (not calling ``build()`` in-process) against a fixture data
root holding one renamed card, mirroring what ``make rebuild-derivatives``
actually invokes.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest(path: Path, cards: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cards": [
                    {"card_id": cid, "title": cid, "asset_type": kind}
                    for cid, kind in cards.items()
                ]
            }
        )
    )


def _ocr(ocr_dir: Path, card_id: str) -> None:
    card_dir = ocr_dir / card_id
    card_dir.mkdir(parents=True)
    (card_dir / "meta.json").write_text(json.dumps({"status": "ok"}))
    (card_dir / "pages.jsonl").write_text(json.dumps({"page": 1, "text": "t"}) + "\n")


_TRANCHE = "ab" * 32


def _aliases(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"aliases": rows}))


def _approval_log(path: Path) -> Path:
    path.write_text(json.dumps({"tranche_sha256": _TRANCHE}) + "\n")
    return path


def test_build_search_data_cli_accepts_approved_rename_without_allow_shrink(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, {"b": "PDF", "c": "PDF"})
    ocr = tmp_path / "ocr"
    _ocr(ocr, "b")
    _ocr(ocr, "c")
    out = tmp_path / "pages.json"
    out.write_text(
        json.dumps(
            [
                {"card_id": "a", "page": 1, "text": "old"},
                {"card_id": "b", "page": 1, "text": "old"},
            ]
        )
    )
    aliases = tmp_path / "card-aliases.json"
    _aliases(
        aliases, [{"old_card_id": "a", "new_card_id": "c", "method": "operator_manual",
          "tranche_sha256": _TRANCHE}]
    )

    result = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "build_search_data.py"),
            "--ocr-dir", str(ocr),
            "--manifest", str(manifest),
            "--out", str(out),
            "--aliases", str(aliases),
            "--approval-log", str(_approval_log(tmp_path / "approvals.jsonl")),
            "--audit-log", str(tmp_path / "audit-log.jsonl"),
            "--allow-override", "--reason", "rehearsal against fixture inputs",
            "--image-observations-index", str(tmp_path / "no-such-index.json"),
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "renamed: a -> c" in result.stdout
    row = json.loads((tmp_path / "audit-log.jsonl").read_text().splitlines()[-1])
    assert (row["old_card_id"], row["new_card_id"]) == ("a", "c")
    assert row["tranche_sha256"] == _TRANCHE


def test_build_embed_data_cli_accepts_approved_rename_without_allow_shrink(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "pages.json").write_text(
        json.dumps(
            [
                {"card_id": "b", "page": 1, "text": "readable"},
                {"card_id": "c", "page": 1, "text": "readable"},
            ]
        )
    )
    (out_dir / "embed_index.json").write_text(
        json.dumps(
            {"model_id": "voyage-3", "dim": 2, "n": 2, "pages": [["a", 1], ["b", 1]]}
        )
    )
    emb_root = tmp_path / "emb"
    in_dir = emb_root / "voyage-3"
    in_dir.mkdir(parents=True)
    card_ids = ["b", "c"]
    flat = [0.5] * (len(card_ids) * 2)
    (in_dir / "vectors.bin").write_bytes(struct.pack(f"<{len(flat)}f", *flat))
    (in_dir / "index.json").write_text(
        json.dumps(
            {
                "model_id": "voyage-3",
                "dim": 2,
                "n": len(card_ids),
                "pages": [
                    {"card_id": cid, "page": 1, "text_sha": "x", "offset": i * 2 * 4}
                    for i, cid in enumerate(card_ids)
                ],
            }
        )
    )
    aliases = tmp_path / "card-aliases.json"
    _aliases(
        aliases, [{"old_card_id": "a", "new_card_id": "c", "method": "operator_manual",
          "tranche_sha256": _TRANCHE}]
    )
    # No PDF cards in the manifest: the coverage rule has nothing to flag,
    # isolating this run to the shrink/rename rule under test.
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, {})

    result = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "build_embed_data.py"),
            "--embeddings-root", str(emb_root),
            "--model", "voyage-3",
            "--out-dir", str(out_dir),
            "--aliases", str(aliases),
            "--approval-log", str(_approval_log(tmp_path / "approvals.jsonl")),
            "--audit-log", str(tmp_path / "audit-log.jsonl"),
            "--allow-override", "--reason", "rehearsal against fixture inputs",
            "--manifest", str(manifest),
            "--ocr-dir", str(tmp_path / "no-ocr"),
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "renamed: a -> c" in result.stdout
    row = json.loads((tmp_path / "audit-log.jsonl").read_text().splitlines()[-1])
    assert (row["old_card_id"], row["new_card_id"]) == ("a", "c")
    assert row["tranche_sha256"] == _TRANCHE
