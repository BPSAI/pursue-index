"""Shared fixtures-free helpers for the image-mirror tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.scrape.types import CardMetadata

runner = CliRunner()

JPG = b"\xff\xd8\xff\xe0 tiny jpg"
PNG = b"\x89PNG tiny png"
JPG_SHA = hashlib.sha256(JPG).hexdigest()
PNG_SHA = hashlib.sha256(PNG).hexdigest()


def _card(cid: str, name: str = "p.jpg", typ: str = "IMG") -> CardMetadata:
    return CardMetadata(
        card_id=cid,
        title=f"t{cid}",
        asset_type=typ,
        agency="FBI",
        asset_url=f"https://example.test/{name}",
        asset_filename=name,
    )


def _registry(path: Path, *rows: tuple[str, str, str]) -> Path:
    """rows: (card_id, sha, archive_key); later rows are newer."""
    path.write_text(
        "".join(
            json.dumps({"card_id": c, "byte_sha256": s, "archive_key": k}) + "\n"
            for c, s, k in rows
        )
    )
    return path


def _put(root: Path, cid: str, name: str, data: bytes) -> None:
    d = root / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)


def _kw(tmp_path: Path, reg: Path) -> dict:
    return dict(
        images_root=tmp_path / "images",
        mirror_root=tmp_path / "r2-mirror",
        registry_path=reg,
    )


def _archive(tmp_path: Path) -> Path:
    return tmp_path / "r2-mirror" / "archive"


A = "a000000000000001"
B = "b000000000000002"
