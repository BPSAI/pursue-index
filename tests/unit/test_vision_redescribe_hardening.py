"""Hardening for the ``--redescribe`` path: check-to-use gaps, duplicate pages,
temp files, markup and date checks. Every test stubs the client; none spends."""

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from pydantic import BaseModel
from rich.console import Console

from pursue_index.config import settings
from pursue_index.scrape.types import CardMetadata, Manifest
from pursue_index.vision import img_source, method_exceptions, render, supersede
from pursue_index.vision.eligibility import EligibleItem, select_eligible
from pursue_index.vision.redescribe import plan_redescribe, redescribe_vision
from tests.unit.test_vision_cli import _img_card

CARD = "613dc8ef961f9399"
OLD_PASS = {"model": "old", "method": "m", "context": "c"}


def _png(color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _manifest(*cards: CardMetadata) -> Manifest:
    return Manifest(
        source_url="https://www.war.gov/uap-csv.csv",
        fetched_at=datetime.now(UTC), csv_sha256="0" * 64, cards=list(cards),
    )


def _sidecar(out: Path, card_id: str, pages: list[dict]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{card_id}.json"
    path.write_text(json.dumps({
        "card_id": card_id, "schema_version": 1, "our_pass": dict(OLD_PASS),
        "pages": pages,
    }), encoding="utf-8")
    return path


@pytest.fixture
def resolve(monkeypatch) -> None:
    from pursue_index.download.downloader import asset_path_for
    from pursue_index.vision import redescribe

    monkeypatch.setattr(
        redescribe, "resolve_img_path", lambda card, registry=None: (asset_path_for(card), None)
    )


# ---- row 1: verify at load -------------------------------------------------

def test_load_refuses_a_file_swapped_after_planning(tmp_path: Path) -> None:
    asset = tmp_path / "m.png"
    asset.write_bytes(_png("white"))
    sha = hashlib.sha256(asset.read_bytes()).hexdigest()
    item = EligibleItem(card_id=CARD, page=1, kind="img_card", image_path=asset,
                        title="t", expected_sha256=sha)
    assert render.load_image_for(item).size == (4, 4)
    asset.write_bytes(_png("black"))  # swapped between plan and load
    with pytest.raises(ValueError, match="sha256"):
        render.load_image_for(item)


def test_mirror_items_carry_the_verified_sha(tmp_path: Path, monkeypatch) -> None:
    data = _png()
    sha = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    registry = tmp_path / "reg.jsonl"
    registry.write_text(json.dumps({"card_id": CARD, "byte_sha256": sha}) + "\n")
    monkeypatch.setattr(img_source, "default_registry_path", lambda: registry)
    mirror = tmp_path / "data" / "r2-mirror" / "archive" / f"{sha}.png"
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes(data)
    card = CardMetadata(card_id=CARD, title="t", asset_type="IMG", agency="FBI",
                        asset_url="https://www.war.gov/x/a.png", asset_filename="a.png")
    items = select_eligible(_manifest(card), {CARD}, tmp_path / "ocr")
    assert items[0].image_path == mirror and items[0].expected_sha256 == sha


# ---- row 2: plan vs write --------------------------------------------------

def test_card_changed_between_plan_and_write_is_refused_by_name(tmp_path, resolve) -> None:
    out = tmp_path / "o"
    path = _sidecar(out, CARD, [{"page": 1, "observations": [{"claim": "old"}]}])
    plan = plan_redescribe(_manifest(_img_card(CARD)), {CARD}, out)
    assert plan.refusals == []
    changed = json.loads(path.read_text())
    changed["operator"] = "someone edited this after planning"
    edited_text = json.dumps(changed)

    def examine(_img):
        path.write_text(edited_text, encoding="utf-8")  # changes mid-run
        return {"observations": [{"claim": "new"}], "description": "d"}

    report = redescribe_vision(
        plan, out, examine_fn=examine, load_image_fn=lambda item: object(),
        budget_usd=5.0,
    )
    assert report.produced == []
    assert report.failures and all(CARD in reason for _k, reason in report.failures)
    assert path.read_text(encoding="utf-8") == edited_text  # never written over


# ---- row 3: duplicate pages ------------------------------------------------

def test_identical_duplicate_pages_are_planned_once(tmp_path, resolve) -> None:
    page = {"page": 1, "row_key": "", "observations": [{"claim": "same"}]}
    _sidecar(tmp_path, CARD, [page, dict(page)])
    plan = plan_redescribe(_manifest(_img_card(CARD)), {CARD}, tmp_path)
    assert plan.refusals == []
    assert len(plan.items_by_card[CARD]) == 1


def test_conflicting_duplicate_pages_refuse_the_card_by_name(tmp_path, resolve) -> None:
    _sidecar(tmp_path, CARD, [
        {"page": 1, "row_key": "", "observations": [{"claim": "one"}]},
        {"page": 1, "row_key": "", "observations": [{"claim": "two"}]},
    ])
    plan = plan_redescribe(_manifest(_img_card(CARD)), {CARD}, tmp_path)
    assert CARD not in plan.items_by_card
    assert len(plan.refusals) == 1 and CARD in plan.refusals[0]


# ---- row 4: mirror hashing -------------------------------------------------

def test_preview_hashes_each_mirror_file_once(tmp_path: Path, monkeypatch) -> None:
    data = _png("red")
    sha = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    registry = tmp_path / "reg.jsonl"
    registry.write_text(json.dumps({"card_id": CARD, "byte_sha256": sha}) + "\n")
    monkeypatch.setattr(img_source, "default_registry_path", lambda: registry)
    mirror = tmp_path / "data" / "r2-mirror" / "archive" / f"{sha}.png"
    mirror.parent.mkdir(parents=True)
    mirror.write_bytes(data)
    calls: list[Path] = []
    real = img_source._file_sha256
    monkeypatch.setattr(img_source, "_file_sha256", lambda p: calls.append(p) or real(p))
    card = CardMetadata(card_id=CARD, title="t", asset_type="IMG", agency="FBI",
                        asset_url="https://www.war.gov/x/a.png", asset_filename="a.png")
    for _ in range(3):
        select_eligible(_manifest(card), {CARD}, tmp_path / "ocr")
    assert len(calls) == 1


# ---- row 5: rich markup ----------------------------------------------------

def test_operator_text_is_printed_literally(tmp_path, monkeypatch) -> None:
    from pursue_index.cli import vision_exceptions as ve

    entry = {"card_id": CARD, "reason": "[bold]curated[/bold]", "cluster_label": "c",
             "decided_at": "2026-11-22"}
    path = tmp_path / "e.json"
    path.write_text(json.dumps({"exceptions": [entry]}))
    monkeypatch.setattr(method_exceptions, "default_exceptions_path", lambda: path)
    buf = io.StringIO()
    monkeypatch.setattr(ve, "console", Console(file=buf, width=300, force_terminal=False))
    ve.check_method_exceptions({CARD}, True, "[red]x[/red]")
    out = buf.getvalue()
    assert "[red]x[/red]" in out and "[bold]curated[/bold]" in out


# ---- row 6: temp files -----------------------------------------------------

def test_failed_write_leaves_no_temp_file_and_target_intact(tmp_path, monkeypatch) -> None:
    target = tmp_path / "card.json"
    target.write_text("original", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(supersede.os, "replace", boom)
    with pytest.raises(OSError):
        supersede.write_atomic(target, {"a": 1})
    assert target.read_text(encoding="utf-8") == "original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card.json"]


def test_unserializable_doc_leaves_no_temp_file(tmp_path) -> None:
    target = tmp_path / "card.json"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(TypeError):
        supersede.write_atomic(target, {"a": {1, 2}})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card.json"]


def test_write_atomic_lands_the_document(tmp_path) -> None:
    target = tmp_path / "card.json"
    supersede.write_atomic(target, {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert not [p for p in tmp_path.iterdir() if p != target]
    assert os.path.exists(target)


def test_write_atomic_keeps_the_existing_mode(tmp_path) -> None:
    target = tmp_path / "card.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o644)
    supersede.write_atomic(target, {"a": 1})
    assert target.stat().st_mode & 0o777 == 0o644
    assert json.loads(target.read_text()) == {"a": 1}


def test_write_atomic_keeps_a_non_default_mode(tmp_path) -> None:
    target = tmp_path / "card.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o640)
    supersede.write_atomic(target, {"a": 1})
    assert target.stat().st_mode & 0o777 == 0o640


def test_write_atomic_creates_a_new_file_0644(tmp_path) -> None:
    target = tmp_path / "card.json"
    supersede.write_atomic(target, {"a": 1})
    assert target.stat().st_mode & 0o777 == 0o644
    assert json.loads(target.read_text()) == {"a": 1}


def test_write_atomic_refuses_a_symlinked_sidecar(tmp_path) -> None:
    real = tmp_path / "real.json"
    real.write_text("original", encoding="utf-8")
    real.chmod(0o600)
    link = tmp_path / "card.json"
    link.symlink_to(real)
    with pytest.raises(OSError, match=r"card\.json"):
        supersede.write_atomic(link, {"a": 1})
    assert link.is_symlink()
    assert os.readlink(link) == str(real)
    assert real.read_text(encoding="utf-8") == "original"
    assert real.stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card.json", "real.json"]


def test_write_atomic_refuses_a_dangling_symlink(tmp_path) -> None:
    link = tmp_path / "card.json"
    link.symlink_to(tmp_path / "missing.json")
    with pytest.raises(OSError, match=r"card\.json"):
        supersede.write_atomic(link, {"a": 1})
    assert link.is_symlink()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card.json"]


def test_write_atomic_syncs_the_file_and_the_directory(tmp_path, monkeypatch) -> None:
    import stat as stat_mod

    kinds: list[bool] = []
    real = os.fsync

    def spy(fd):
        kinds.append(stat_mod.S_ISDIR(os.fstat(fd).st_mode))
        real(fd)

    monkeypatch.setattr(supersede.os, "fsync", spy)
    supersede.write_atomic(tmp_path / "card.json", {"a": 1})
    assert kinds == [False, True]  # the file before the replace, the directory after


def test_write_card_refuses_when_the_planned_copy_is_missing(tmp_path) -> None:
    from pursue_index.vision.redescribe import RedescribePlan, _write_card

    path = _sidecar(tmp_path, CARD, [])
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match=CARD):
        _write_card(RedescribePlan(), CARD, path, [], "m", "now")
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


# ---- row 7: placeholders follow the page model -----------------------------

def test_schema_change_fails_the_dry_run(monkeypatch) -> None:
    class StricterPage(BaseModel):
        page: int
        observations: list[dict]
        new_required_field: str

    existing = {"card_id": CARD, "schema_version": 1, "our_pass": dict(OLD_PASS),
                "pages": [{"page": 1, "observations": [{"claim": "old"}]}]}
    items = [EligibleItem(card_id=CARD, page=1, kind="img_card", image_path=None, title="t")]
    assert supersede.dry_supersede(existing, items, "m") is None
    monkeypatch.setattr(supersede, "SidecarPage", StricterPage)
    why = supersede.dry_supersede(existing, items, "m")
    assert why is not None and "new_required_field" in why


# ---- row 8: decided_at -----------------------------------------------------

@pytest.mark.parametrize("bad", ["yesterday", "2026-13-01", "2026-11-22T10:00:00", "22/11/2026"])
def test_malformed_decided_at_fails_closed(tmp_path, monkeypatch, bad) -> None:
    entry = {"card_id": CARD, "reason": "r", "cluster_label": "c", "decided_at": bad}
    path = tmp_path / "e.json"
    path.write_text(json.dumps({"exceptions": [entry]}))
    with pytest.raises(method_exceptions.MethodExceptionsError, match="decided_at"):
        method_exceptions.load_method_exceptions(path)
