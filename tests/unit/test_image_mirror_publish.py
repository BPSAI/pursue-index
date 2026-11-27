"""Exclusive publish: raced targets are never overwritten; no temp files left."""

from __future__ import annotations

from pursue_index.release.image_mirror import run_image_mirror
from tests.unit._image_mirror_helpers import (
    JPG,
    JPG_SHA,
    A,
    _archive,
    _card,
    _kw,
    _put,
    _registry,
)

# --- exclusive publish ----------------------------------------------------


def _race_setup(tmp_path, monkeypatch, planted: bytes):
    """Create the target between the existence check and the publish."""
    import shutil

    from pursue_index.release import image_mirror as im

    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    target = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    real_copy = shutil.copy2

    def copy_then_plant(src, dst, *a, **k):
        out = real_copy(src, dst, *a, **k)
        target.write_bytes(planted)
        return out

    monkeypatch.setattr(im.shutil, "copy2", copy_then_plant)
    return reg, target


def test_target_created_during_publish_is_never_overwritten(tmp_path, monkeypatch):
    reg, target = _race_setup(tmp_path, monkeypatch, b"someone else's bytes")
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.counts["target_mismatch"] == 1 and not rep.ok
    assert target.read_bytes() == b"someone else's bytes"
    assert not list(_archive(tmp_path).glob("*.tmp"))


def test_target_created_during_publish_with_same_bytes_is_already_present(tmp_path, monkeypatch):
    reg, target = _race_setup(tmp_path, monkeypatch, JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.counts["already_present"] == 1 and rep.ok
    assert target.read_bytes() == JPG
    assert not list(_archive(tmp_path).glob("*.tmp"))


def _no_hard_links(monkeypatch):
    import errno
    import os

    def refuse(*_a, **_k):
        raise OSError(errno.EPERM, "hard links not supported")

    monkeypatch.setattr(os, "link", refuse)


def test_hard_link_refused_falls_back_to_exclusive_create(tmp_path, monkeypatch):
    _no_hard_links(monkeypatch)
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.ok and rep.counts["mirrored"] == 1
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").read_bytes() == JPG
    assert not list(_archive(tmp_path).glob("*.tmp"))


def test_fallback_publish_never_overwrites_a_raced_target(tmp_path, monkeypatch):
    _no_hard_links(monkeypatch)
    reg, target = _race_setup(tmp_path, monkeypatch, b"someone else's bytes")
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.counts["target_mismatch"] == 1
    assert target.read_bytes() == b"someone else's bytes"
    assert not list(_archive(tmp_path).glob("*.tmp"))


def test_no_temp_file_left_after_a_normal_publish(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert [p.name for p in _archive(tmp_path).iterdir()] == [f"{JPG_SHA}.jpg"]


def test_symlink_at_the_old_predictable_temp_path_is_never_followed(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"do not touch")
    _archive(tmp_path).mkdir(parents=True)
    (_archive(tmp_path) / f"{JPG_SHA}.jpg.tmp").symlink_to(victim)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert victim.read_bytes() == b"do not touch"
    assert rep.ok and rep.counts["mirrored"] == 1
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").read_bytes() == JPG
