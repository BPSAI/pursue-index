"""Image mirror: a symlink at the target is its own outcome; the source opens without following."""

from __future__ import annotations

import pytest

from pursue_index.release import image_mirror as im
from pursue_index.release.image_mirror import run_image_mirror
from pursue_index.release.image_mirror_render import render_image_mirror_report
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


def _reg(tmp_path):
    return _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (B, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )


def _row(results: dict, cid: str):
    (hit,) = [v for k, v in results.items() if k.startswith(cid)]
    return hit


def _both(tmp_path):
    _put(tmp_path / "images", A, "p.jpg", JPG)
    _put(tmp_path / "images", B, "q.png", PNG)
    _archive(tmp_path).mkdir(parents=True)


# --- 1. unsafe_target -----------------------------------------------------


def test_dangling_target_symlink_is_unsafe_target(tmp_path):
    reg = _reg(tmp_path)
    _both(tmp_path)
    link = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    link.symlink_to(tmp_path / "nowhere.jpg")
    rep = run_image_mirror([_card(A), _card(B, "q.png")], **_kw(tmp_path, reg))
    assert rep.counts.get("unsafe_target", 0) == 1 and rep.counts["mirrored"] == 1
    assert rep.counts["target_mismatch"] == 0 and not rep.ok
    assert "symlink" in _row(rep.results, A)[1]
    assert link.is_symlink() and not (tmp_path / "nowhere.jpg").exists()
    assert "unsafe_target" in render_image_mirror_report(rep)


@pytest.mark.parametrize("held", [b"other bytes", JPG], ids=["differing", "matching"])
def test_live_target_symlink_is_unsafe_target_and_not_written_through(tmp_path, held):
    reg = _reg(tmp_path)
    _both(tmp_path)
    real = tmp_path / "elsewhere.bin"
    real.write_bytes(held)
    link = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    link.symlink_to(real)
    rep = run_image_mirror([_card(A), _card(B, "q.png")], **_kw(tmp_path, reg))
    assert _row(rep.results, A)[0] == "unsafe_target"
    assert rep.counts["mirrored"] == 1 and not rep.ok
    assert link.is_symlink() and real.read_bytes() == held
    assert not list(_archive(tmp_path).glob("*.tmp"))


def test_real_mismatched_target_file_is_still_target_mismatch(tmp_path):
    reg = _reg(tmp_path)
    _both(tmp_path)
    (_archive(tmp_path) / f"{JPG_SHA}.jpg").write_bytes(b"different")
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert _row(rep.results, A)[0] == "target_mismatch"
    assert rep.counts.get("unsafe_target", 0) == 0


# --- 2. source opened with O_NOFOLLOW -------------------------------------


def test_source_swapped_to_a_symlink_after_the_check_is_unsafe_source(tmp_path, monkeypatch):
    reg = _reg(tmp_path)
    _both(tmp_path)
    decoy = tmp_path / "decoy.jpg"
    decoy.write_bytes(JPG)  # same bytes: a followed link would mirror cleanly
    real_check = im._source_path

    def swap_after_check(card, images_root):
        src = real_check(card, images_root)
        if card.card_id == A and not isinstance(src, str):
            src.unlink()
            src.symlink_to(decoy)
        return src

    monkeypatch.setattr(im, "_source_path", swap_after_check)
    rep = run_image_mirror([_card(A), _card(B, "q.png")], **_kw(tmp_path, reg))
    outcome, detail = _row(rep.results, A)
    assert outcome == "unsafe_source" and "symlink at open time" in detail
    assert rep.counts["mirrored"] == 1 and not rep.ok
    assert not (_archive(tmp_path) / f"{JPG_SHA}.jpg").exists()
    assert not list(_archive(tmp_path).glob("*.tmp"))
