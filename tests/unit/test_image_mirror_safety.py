"""Unsafe sources, the one mirror path rule, bad archive keys, extension allowlist."""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.release.image_mirror import run_image_mirror, verify_image_mirror
from pursue_index.vision import img_source
from pursue_index.vision.img_source import (
    BadArchiveKeyError,
    load_registry,
    mirror_path_for,
)
from tests.unit._image_mirror_helpers import (
    JPG,
    JPG_SHA,
    PNG,
    PNG_SHA,
    A,
    B,
    _archive,
    _card,
    _kw,
    _put,
    _registry,
)

# --- unsafe source fields -------------------------------------------------


def _outside(tmp_path: Path) -> Path:
    out = tmp_path / "outside.jpg"
    out.write_bytes(JPG)
    return out


@pytest.mark.parametrize("kind", ["absolute", "dotdot", "slash", "backslash", "empty", "dot"])
def test_unsafe_asset_filename_is_refused(tmp_path, kind):
    name = {
        "absolute": str(_outside(tmp_path)),
        "dotdot": "../../outside.jpg",
        "slash": "a/b.jpg",
        "backslash": "a\\b.jpg",
        "empty": "",
        "dot": "..",
    }[kind]
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    card = _card(A, "p.jpg").model_copy(update={"asset_filename": name})
    rep = run_image_mirror([card], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["unsafe_source"] == 1
    assert not _archive(tmp_path).exists()


@pytest.mark.parametrize("bad", ["../x", "/abs", "A000000000000001", "short", ""])
def test_unsafe_card_id_is_refused(tmp_path, bad):
    reg = _registry(tmp_path / "reg.jsonl", (bad, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    (tmp_path / "images").mkdir()
    rep = run_image_mirror([_card(bad)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["unsafe_source"] == 1
    assert not _archive(tmp_path).exists()


# --- one mirror path rule -------------------------------------------------


def test_mirror_path_for_good_key(tmp_path):
    key = f"archive/{JPG_SHA}.jpg"
    row = {"byte_sha256": JPG_SHA, "archive_key": key}
    assert mirror_path_for(tmp_path, row) == tmp_path / key


@pytest.mark.parametrize(
    "key",
    [
        f"archive/{PNG_SHA}.jpg",  # sha differs from the row's
        f"other/{JPG_SHA}.jpg",  # wrong prefix
        f"archive/{JPG_SHA}",  # no extension
        f"archive/{JPG_SHA}.",  # empty extension
        f"archive/../{JPG_SHA}.jpg",
        f"archive/{JPG_SHA.upper()}.jpg",
        "",
        None,
    ],
)
def test_mirror_path_for_rejects_bad_keys(tmp_path, key):
    with pytest.raises(BadArchiveKeyError):
        mirror_path_for(tmp_path, {"byte_sha256": JPG_SHA, "archive_key": key})


def test_bad_archive_key_outcome_writes_nothing(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{PNG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["bad_archive_key"] == 1
    assert not _archive(tmp_path).exists()
    pf = verify_image_mirror([_card(A)], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert not pf.ok


def test_writer_verifier_and_vision_reader_agree(tmp_path, monkeypatch):
    # asset_filename says .JPG; the registry's archive_key says .jpg.
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "P.JPG", JPG)
    card = _card(A, "P.JPG")
    rep = run_image_mirror([card], **_kw(tmp_path, reg))
    assert rep.ok
    expected = tmp_path / "r2-mirror" / "archive" / f"{JPG_SHA}.jpg"
    assert expected.is_file()
    pf = verify_image_mirror([card], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert pf.ok
    monkeypatch.setattr(img_source.settings, "data_root", tmp_path)
    path, why = img_source._mirror_path(card, load_registry(reg))
    assert why is None and path == expected


# --- per-row guards -------------------------------------------------------


def test_row_outside_images_dir_is_unsafe_and_batch_continues(tmp_path, monkeypatch):
    from pursue_index.release import image_mirror as im

    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    _put(tmp_path / "images", B, "q.png", PNG)
    real = im.asset_path_for
    monkeypatch.setattr(
        im,
        "asset_path_for",
        lambda c: Path("/elsewhere/x.jpg") if c.card_id == A else real(c),
    )
    rep = run_image_mirror([_card(A), _card(B, "q.png")], **_kw(tmp_path, reg))
    assert rep.counts["unsafe_source"] == 1
    assert rep.counts["mirrored"] == 1


@pytest.mark.parametrize("ext", ["pdf", "exe", "PDF", "svg"])
def test_non_image_extension_is_bad_archive_key(tmp_path, ext):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.{ext}"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.counts["bad_archive_key"] == 1
    assert not _archive(tmp_path).exists()
    pf = verify_image_mirror([_card(A)], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert not pf.ok


@pytest.mark.parametrize("ext", ["JPG", "jpeg", "gif", "webp", "tif", "tiff", "PNG"])
def test_image_extensions_accepted_case_insensitively(tmp_path, ext):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.{ext}"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.ok and rep.counts["mirrored"] == 1
