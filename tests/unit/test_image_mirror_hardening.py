"""Image mirror hardening: dangling links, per-row I/O errors, one IMG path rule, legacy rows."""

from __future__ import annotations

import hashlib
import json

import pytest

from pursue_index.release import image_mirror as im
from pursue_index.release.image_mirror import run_image_mirror, verify_image_mirror
from pursue_index.vision import img_source
from pursue_index.vision.img_source import (
    BadArchiveKeyError,
    img_mirror_path_for,
    load_registry,
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

C = "c000000000000003"
GIF = b"GIF89a tiny gif"
GIF_SHA = hashlib.sha256(GIF).hexdigest()


def _row(results: dict, cid: str):
    """The one entry whose row key starts with ``cid`` (keys are ``<id>#<n>``)."""
    (hit,) = [v for k, v in results.items() if k.startswith(cid)]
    return hit


def _run(cards, tmp_path, reg):
    """Run the stage; a raised OSError (an aborted batch) is a test failure."""
    try:
        return run_image_mirror(cards, **_kw(tmp_path, reg))
    except OSError as exc:
        pytest.fail(f"the batch aborted on {type(exc).__name__}: {exc}")


# --- 1. dangling symlinks -------------------------------------------------


def test_dangling_source_symlink_is_unsafe_source_and_batch_continues(tmp_path):
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    (tmp_path / "images" / A).mkdir(parents=True)
    (tmp_path / "images" / A / "p.jpg").symlink_to(tmp_path / "nowhere.jpg")
    _put(tmp_path / "images", B, "q.png", PNG)
    rep = _run([_card(A), _card(B, "q.png")], tmp_path, reg)
    assert rep.counts["unsafe_source"] == 1 and rep.counts["mirrored"] == 1
    assert "dangling symlink" in _row(rep.results, A)[1]
    assert not rep.ok
    assert not (tmp_path / "nowhere.jpg").exists()


def test_dangling_target_symlink_is_unsafe_target_and_never_written_through(tmp_path):
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    _put(tmp_path / "images", A, "p.jpg", JPG)
    _put(tmp_path / "images", B, "q.png", PNG)
    _archive(tmp_path).mkdir(parents=True)
    link = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    link.symlink_to(tmp_path / "nowhere.jpg")
    rep = _run([_card(A), _card(B, "q.png")], tmp_path, reg)
    assert rep.counts["unsafe_target"] == 1 and rep.counts["mirrored"] == 1
    assert "symlink" in _row(rep.results, A)[1]
    assert link.is_symlink() and not (tmp_path / "nowhere.jpg").exists()
    assert not list(_archive(tmp_path).glob("*.tmp"))
    pf = verify_image_mirror([_card(A)], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert not pf.ok


# --- 2. per-row I/O guard -------------------------------------------------


def test_oserror_on_one_row_is_io_error_and_the_next_row_mirrors(tmp_path, monkeypatch):
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    _put(tmp_path / "images", A, "p.jpg", JPG)
    _put(tmp_path / "images", B, "q.png", PNG)
    real = im.stage_temp

    def flaky(src, target):
        if target.name.startswith(JPG_SHA):  # row A; the stage now takes the open source
            raise OSError(5, "Input/output error")
        return real(src, target)

    monkeypatch.setattr(im, "stage_temp", flaky)
    rep = _run([_card(A), _card(B, "q.png")], tmp_path, reg)
    assert rep.counts["io_error"] == 1 and rep.counts["mirrored"] == 1
    assert not rep.ok
    assert (_archive(tmp_path) / f"{PNG_SHA}.png").read_bytes() == PNG


def test_oserror_in_the_verifier_is_a_failing_row_not_an_abort(tmp_path, monkeypatch):
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    (_archive(tmp_path)).mkdir(parents=True)
    (_archive(tmp_path) / f"{JPG_SHA}.jpg").write_bytes(JPG)
    (_archive(tmp_path) / f"{PNG_SHA}.png").write_bytes(b"wrong")
    real = im.sha256_file

    def flaky(path):
        if path.name.startswith(JPG_SHA):
            raise OSError(5, "Input/output error")
        return real(path)

    monkeypatch.setattr(im, "sha256_file", flaky)
    pf = verify_image_mirror(
        [_card(A), _card(B, "q.png")], mirror_root=tmp_path / "r2-mirror", registry_path=reg
    )
    assert not pf.ok and len(pf.details) == 2
    assert "io_error" in _row(pf.details, A) and "sha mismatch" in _row(pf.details, B)


def test_a_programming_error_still_raises(tmp_path, monkeypatch):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)

    def boom(src, target):
        raise ValueError("a bug")

    monkeypatch.setattr(im, "stage_temp", boom)
    with pytest.raises(ValueError):
        run_image_mirror([_card(A)], **_kw(tmp_path, reg))


# --- 3. the allowlist lives in the shared helper --------------------------


def test_helper_refuses_a_non_image_extension_for_img_rows(tmp_path):
    row = {"byte_sha256": JPG_SHA, "archive_key": f"archive/{JPG_SHA}.exe"}
    with pytest.raises(BadArchiveKeyError):
        img_mirror_path_for(tmp_path, row)
    ok = {"byte_sha256": JPG_SHA, "archive_key": f"archive/{JPG_SHA}.JPG"}
    assert img_mirror_path_for(tmp_path, ok) == tmp_path / f"archive/{JPG_SHA}.JPG"


def test_exe_key_is_refused_by_writer_verifier_and_vision_reader(tmp_path, monkeypatch):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.exe"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    planted = _archive(tmp_path) / f"{JPG_SHA}.exe"
    planted.parent.mkdir(parents=True)
    planted.write_bytes(JPG)  # sha-correct bytes sit at the .exe path
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.counts["bad_archive_key"] == 1
    pf = verify_image_mirror([_card(A)], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert not pf.ok
    monkeypatch.setattr(img_source.settings, "data_root", tmp_path)
    path, why = img_source._mirror_path(_card(A), load_registry(reg))
    assert path is None and why


# --- 4. legacy rows without an archive_key --------------------------------


def _legacy_registry(path, *rows):
    path.write_text("".join(json.dumps({"card_id": c, "byte_sha256": s}) + "\n" for c, s in rows))
    return path


def test_legacy_row_mirrors_to_the_path_the_vision_reader_resolves(tmp_path, monkeypatch):
    reg = _legacy_registry(tmp_path / "reg.jsonl", (A, GIF_SHA))
    _put(tmp_path / "images", A, "g.gif", GIF)
    card = _card(A, "g.gif")
    rep = run_image_mirror([card], **_kw(tmp_path, reg))
    assert rep.ok and rep.counts["mirrored"] == 1
    expected = _archive(tmp_path) / f"{GIF_SHA}.gif"
    assert expected.read_bytes() == GIF
    pf = verify_image_mirror([card], mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    assert pf.ok
    monkeypatch.setattr(img_source.settings, "data_root", tmp_path)
    path, why = img_source._mirror_path(card, load_registry(reg))
    assert why is None and path == expected


def test_legacy_row_with_a_non_image_asset_extension_is_refused(tmp_path):
    reg = _legacy_registry(tmp_path / "reg.jsonl", (A, JPG_SHA))
    _put(tmp_path / "images", A, "p.exe", JPG)
    rep = run_image_mirror([_card(A, "p.exe")], **_kw(tmp_path, reg))
    assert rep.counts["bad_archive_key"] == 1
    assert not _archive(tmp_path).exists()


def test_legacy_row_is_still_sha_verified(tmp_path):
    reg = _legacy_registry(tmp_path / "reg.jsonl", (A, PNG_SHA))
    _put(tmp_path / "images", A, "p.png", b"not the registered bytes")
    rep = run_image_mirror([_card(A, "p.png")], **_kw(tmp_path, reg))
    assert rep.counts["sha_mismatch"] == 1
    assert not _archive(tmp_path).exists()
