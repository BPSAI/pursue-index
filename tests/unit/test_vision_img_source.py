"""IMG cards fall back to the verified R2 mirror when ``images/`` lacks the file.

Fixture bytes in temp dirs only; nothing here touches the NAS or the network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pursue_index.config import settings
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.vision import img_source
from pursue_index.vision.eligibility import select_eligible
from pursue_index.vision.redescribe import plan_redescribe

CARD = "613dc8ef961f9399"
BYTES = b"\x89PNG fixture bytes"
SHA = hashlib.sha256(BYTES).hexdigest()


def _card() -> CardMetadata:
    return CardMetadata(
        card_id=CARD, title="FBI Photo A5", asset_type="IMG", agency="FBI",
        asset_url="https://www.war.gov/x/fbi-photo-a5.png",
        asset_filename="fbi-photo-a5.png",
    )


def _manifest() -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC), csv_sha256="0" * 64, cards=[_card()],
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    root = tmp_path / "data"
    monkeypatch.setattr(settings, "data_root", root)
    registry = tmp_path / "registry.jsonl"
    monkeypatch.setattr(img_source, "default_registry_path", lambda: registry)
    obs = tmp_path / "obs"
    obs.mkdir()
    (obs / f"{CARD}.json").write_text(json.dumps({
        "card_id": CARD, "our_pass": {}, "pages": [{"page": 1, "observations": []}],
    }))
    return {"root": root, "registry": registry, "obs": obs}


def _registry(path: Path, *rows: tuple[str, str]) -> None:
    path.write_text("".join(
        json.dumps({"card_id": c, "byte_sha256": s}) + "\n" for c, s in rows
    ))


def _mirror(root: Path, sha: str, data: bytes = BYTES) -> Path:
    p = root / "r2-mirror" / "archive" / f"{sha}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _images(root: Path) -> Path:
    p = root / "images" / CARD / "fbi-photo-a5.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"images copy")
    return p


def test_mirror_fallback_is_used_and_verified(world) -> None:
    _registry(world["registry"], (CARD, SHA))
    mirror = _mirror(world["root"], SHA)
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert plan.refusals == []
    assert plan.items_by_card[CARD][0].image_path == mirror


def test_newest_registry_row_wins(world) -> None:
    _registry(world["registry"], (CARD, "f" * 64), ("other", "e" * 64), (CARD, SHA))
    mirror = _mirror(world["root"], SHA)
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert plan.items_by_card[CARD][0].image_path == mirror


def test_sha_mismatch_is_refused_by_name(world) -> None:
    _registry(world["registry"], (CARD, SHA))
    _mirror(world["root"], SHA, data=b"corrupt")
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert CARD not in plan.items_by_card
    assert len(plan.refusals) == 1
    assert CARD in plan.refusals[0] and "sha256" in plan.refusals[0]


def test_missing_registry_row_is_refused_by_name(world) -> None:
    _registry(world["registry"], ("other", SHA))
    _mirror(world["root"], SHA)
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert CARD not in plan.items_by_card
    assert len(plan.refusals) == 1
    assert CARD in plan.refusals[0] and "registry" in plan.refusals[0]


def test_absent_mirror_file_is_refused_by_name(world) -> None:
    _registry(world["registry"], (CARD, SHA))
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert len(plan.refusals) == 1 and CARD in plan.refusals[0]


def test_images_copy_takes_precedence(world) -> None:
    _registry(world["registry"], (CARD, SHA))
    _mirror(world["root"], SHA)
    images = _images(world["root"])
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert plan.items_by_card[CARD][0].image_path == images


def test_images_copy_needs_no_registry(world) -> None:
    images = _images(world["root"])
    plan = plan_redescribe(_manifest(), {CARD}, world["obs"])
    assert plan.refusals == []
    assert plan.items_by_card[CARD][0].image_path == images


def test_run_path_uses_verified_mirror(world, tmp_path: Path) -> None:
    _registry(world["registry"], (CARD, SHA))
    mirror = _mirror(world["root"], SHA)
    items = select_eligible(_manifest(), {CARD}, tmp_path / "ocr")
    assert [i.image_path for i in items] == [mirror]


def test_run_path_keeps_images_path_when_mirror_unverified(world, tmp_path: Path) -> None:
    _registry(world["registry"], (CARD, SHA))
    _mirror(world["root"], SHA, data=b"corrupt")
    items = select_eligible(_manifest(), {CARD}, tmp_path / "ocr")
    assert [i.image_path for i in items] == [world["root"] / "images" / CARD / "fbi-photo-a5.png"]
