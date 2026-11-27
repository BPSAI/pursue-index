"""CLI scoping for the image-mirror verbs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pursue_index.cli import storage_cli
from pursue_index.cli.commands import app
from pursue_index.release.image_mirror import select_image_cards
from tests.unit._image_mirror_helpers import (
    JPG,
    JPG_SHA,
    PNG,
    PNG_SHA,
    _archive,
    _card,
    _put,
    _registry,
    runner,
)

# --- CLI -----------------------------------------------------------------

I1, I2 = "c000000000000001", "c000000000000002"
P1 = "d000000000000001"


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    cards = [_card(I1), _card(I2, "q.png"), _card(P1, "d.pdf", "PDF")]
    manifest = SimpleNamespace(csv_sha256="f" * 64, cards=cards)
    monkeypatch.setattr(storage_cli, "load_manifest", lambda _p: manifest)
    monkeypatch.setattr(
        storage_cli,
        "default_registry_path",
        lambda: _registry(
            tmp_path / "reg.jsonl",
            (I1, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
            (I2, PNG_SHA, f"archive/{PNG_SHA}.png"),
        ),
    )
    monkeypatch.setattr(storage_cli.settings, "data_root", tmp_path)
    _put(tmp_path / "images", I1, "p.jpg", JPG)
    _put(tmp_path / "images", I2, "q.png", PNG)
    wl = tmp_path / "wl.txt"
    wl.write_text(f"# tranche: {'f' * 64}\n{I1}\n{P1}\n")
    return tmp_path, wl


def test_cli_worklist_skips_non_img_and_counts(cli_env):
    tmp_path, wl = cli_env
    r = runner.invoke(app, ["storage", "mirror-images", "--worklist", str(wl)])
    assert r.exit_code == 0, r.output
    assert "[scope]" in r.output and "skipped 1" in r.output
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").is_file()
    assert not (_archive(tmp_path) / f"{PNG_SHA}.png").exists()
    v = runner.invoke(app, ["storage", "verify-image-mirror", "--worklist", str(wl)])
    assert v.exit_code == 0, v.output


def test_cli_all_image_cards_picks_every_img(cli_env):
    tmp_path, _ = cli_env
    r = runner.invoke(app, ["storage", "mirror-images", "--all-image-cards"])
    assert r.exit_code == 0, r.output
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").is_file()
    assert (_archive(tmp_path) / f"{PNG_SHA}.png").is_file()
    v = runner.invoke(app, ["storage", "verify-image-mirror", "--all-image-cards"])
    assert v.exit_code == 0, v.output


def test_cli_verify_fails_when_not_mirrored(cli_env):
    r = runner.invoke(app, ["storage", "verify-image-mirror", "--all-image-cards"])
    assert r.exit_code == 1, r.output


def test_cli_all_image_cards_with_worklist_is_an_error(cli_env):
    _, wl = cli_env
    for verb in ("mirror-images", "verify-image-mirror"):
        r = runner.invoke(app, ["storage", verb, "--all-image-cards", "--worklist", str(wl)])
        assert r.exit_code == 2, r.output
    r = runner.invoke(app, ["storage", "mirror-images"])
    assert r.exit_code == 2, r.output


def test_cli_all_image_cards_refuses_bad_card_id(cli_env, monkeypatch):
    _, _ = cli_env
    bad = _card("../../etc", "p.jpg")
    manifest = storage_cli.load_manifest(None)
    monkeypatch.setattr(
        storage_cli,
        "load_manifest",
        lambda _p: SimpleNamespace(csv_sha256="f" * 64, cards=[*manifest.cards, bad]),
    )
    r = runner.invoke(app, ["storage", "mirror-images", "--all-image-cards"])
    assert r.exit_code == 1, r.output
    assert "unsafe_source" in r.output


# --- scoping fails closed -------------------------------------------------


def test_select_unknown_and_untyped_cards_stay_in_scope():
    rows = [
        {"card_id": "i1", "asset_type": "IMG"},
        {"card_id": "n1"},
        {"card_id": "p1", "asset_type": "PDF"},
    ]
    in_scope, skipped = select_image_cards(["i1", "ghost", "n1", "p1"], rows)
    assert in_scope == ["i1", "ghost", "n1"]
    assert skipped == {"p1": "PDF"}


def test_cli_unknown_card_stays_in_scope_and_verify_fails(cli_env):
    tmp_path, _ = cli_env
    ghost = "e000000000000009"
    wl = tmp_path / "wl2.txt"
    wl.write_text(f"# tranche: {'f' * 64}\n{I1}\n{ghost}\n")
    for verb in ("mirror-images", "verify-image-mirror"):
        r = runner.invoke(app, ["storage", verb, "--worklist", str(wl)])
        assert r.exit_code == 1, r.output
        assert ghost in r.output


def test_cli_known_pdf_is_skipped_and_counted(cli_env):
    _tmp_path, wl = cli_env
    r = runner.invoke(app, ["storage", "mirror-images", "--worklist", str(wl)])
    assert r.exit_code == 0, r.output
    assert "skipped 1" in r.output


def test_cli_all_image_cards_prints_scope_line(cli_env):
    r = runner.invoke(app, ["storage", "mirror-images", "--all-image-cards"])
    assert "[scope] --all-image-cards: 2 IMG cards from the manifest (no tranche gate)" in r.output


# --- a manifest row with no asset_type stays gated ------------------------


def test_cli_worklist_card_without_asset_type_fails_verify(cli_env, monkeypatch):
    tmp_path, _ = cli_env
    untyped = "e000000000000007"
    manifest = storage_cli.load_manifest(None)
    row = {"card_id": untyped}
    manifest.cards.append(SimpleNamespace(card_id=untyped, asset_type=None, model_dump=lambda: row))
    wl = tmp_path / "wl3.txt"
    wl.write_text(f"# tranche: {'f' * 64}\n{I1}\n{untyped}\n")
    runner.invoke(app, ["storage", "mirror-images", "--worklist", str(wl)])
    v = runner.invoke(app, ["storage", "verify-image-mirror", "--worklist", str(wl)])
    assert v.exit_code == 1, v.output
    assert untyped in v.output
