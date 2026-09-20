"""Fixture manifest + registry + data root for the release-completeness tests."""

from __future__ import annotations

import json
from pathlib import Path

import check_release_completeness as crc
import pytest

AUD = "a" * 16
VID = "b" * 16


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def registry_row(card_id: str, ext: str = "mp4") -> dict:
    return {"card_id": card_id, "current_key": f"{card_id}.{ext}"}


class Env:
    """A fixture manifest + registry + data root, with the flags to point at them."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_root = root / "dataroot"
        self.ocr_dir = self.data_root / "ocr"
        self.ocr_dir.mkdir(parents=True)
        self.manifest = root / "latest.json"
        self.registry = root / "registry.jsonl"
        self.waivers = root / "waivers.jsonl"
        self.set_cards({})
        self.set_registry([])

    def set_cards(self, cards: dict[str, str]) -> None:
        rows = [{"card_id": cid, "asset_type": t, "title": f"t-{cid}"} for cid, t in cards.items()]
        self.manifest.write_text(json.dumps({"cards": rows}), encoding="utf-8")

    def set_registry(self, rows: list[dict]) -> None:
        write_jsonl(self.registry, rows)

    def sidecar(self, card_id: str, engine: str = "assemblyai") -> None:
        card_dir = self.ocr_dir / card_id
        card_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(
            card_dir / "pages.jsonl",
            [
                {
                    "page": 1,
                    "text": "Speaker A: hello there",
                    "confidence": 100.0,
                    "engine": engine,
                },
            ],
        )

    def run(self, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
        code = crc.main(
            [
                "--manifest",
                str(self.manifest),
                "--data-root",
                str(self.data_root),
                "--registry",
                str(self.registry),
                "--waivers",
                str(self.waivers),
            ]
        )
        captured = capsys.readouterr()
        return code, captured.out + captured.err
