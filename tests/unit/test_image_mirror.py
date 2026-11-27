"""NAS r2-mirror stage for IMG cards: images/<card>/<file> -> archive/<sha>.<ext>."""

from __future__ import annotations

from pursue_index.release.image_mirror import (
    run_image_mirror,
    select_image_cards,
    verify_image_mirror,
)
from pursue_index.release.image_mirror_render import (
    render_image_mirror_report,
    render_image_verify,
)
from tests.unit._image_mirror_helpers import (
    JPG,
    JPG_SHA,
    PNG,
    PNG_SHA,
    A,
    _archive,
    _card,
    _kw,
    _put,
    _registry,
)


def test_mirrored(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.ok and rep.counts["mirrored"] == 1
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").read_bytes() == JPG
    assert not list(_archive(tmp_path).glob("*.tmp"))


def test_idempotent_second_run_writes_nothing(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    target = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    before = target.stat().st_mtime_ns
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.ok and rep.counts["already_present"] == 1
    assert rep.counts["mirrored"] == 0
    assert target.stat().st_mtime_ns == before


def test_source_missing(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["source_missing"] == 1
    assert not _archive(tmp_path).exists() or not list(_archive(tmp_path).iterdir())


def test_sha_mismatch_writes_nothing(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", b"corrupt bytes")
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["sha_mismatch"] == 1
    assert not _archive(tmp_path).exists() or not list(_archive(tmp_path).iterdir())


def test_target_mismatch_never_overwritten(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    _archive(tmp_path).mkdir(parents=True)
    target = _archive(tmp_path) / f"{JPG_SHA}.jpg"
    target.write_bytes(b"someone else")
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["target_mismatch"] == 1
    assert target.read_bytes() == b"someone else"


def test_extension_follows_archive_key(tmp_path):
    b = "b000000000000002"
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (b, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    _put(tmp_path / "images", A, "p.jpg", JPG)
    _put(tmp_path / "images", b, "q.png", PNG)
    rep = run_image_mirror([_card(A), _card(b, "q.png")], **_kw(tmp_path, reg))
    assert rep.ok
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").is_file()
    assert (_archive(tmp_path) / f"{PNG_SHA}.png").is_file()


def test_newest_registry_row_wins(tmp_path):
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, PNG_SHA, f"archive/{PNG_SHA}.jpg"),  # stale
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),  # newest
    )
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert rep.ok
    assert (_archive(tmp_path) / f"{JPG_SHA}.jpg").is_file()
    assert not (_archive(tmp_path) / f"{PNG_SHA}.jpg").exists()


def test_no_registry_row_fails(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl")
    _put(tmp_path / "images", A, "p.jpg", JPG)
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    assert not rep.ok and rep.counts["no_registry_row"] == 1


def test_verify_passes_and_fails(tmp_path):
    b = "b000000000000002"
    reg = _registry(
        tmp_path / "reg.jsonl",
        (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"),
        (b, PNG_SHA, f"archive/{PNG_SHA}.png"),
    )
    kw = dict(mirror_root=tmp_path / "r2-mirror", registry_path=reg)
    cards = [_card(A), _card(b, "q.png")]
    _archive(tmp_path).mkdir(parents=True)
    (_archive(tmp_path) / f"{JPG_SHA}.jpg").write_bytes(JPG)
    pf = verify_image_mirror(cards, **kw)
    assert not pf.ok and list(pf.details) == [f"{b}#0"]
    assert f"{b}#0" in render_image_verify(pf)
    (_archive(tmp_path) / f"{PNG_SHA}.png").write_bytes(b"wrong")
    pf = verify_image_mirror(cards, **kw)
    assert not pf.ok and list(pf.details) == [f"{b}#0"]
    (_archive(tmp_path) / f"{PNG_SHA}.png").write_bytes(PNG)
    pf = verify_image_mirror(cards, **kw)
    assert pf.ok
    assert "yes" in render_image_verify(pf)


def test_render_report(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    rep = run_image_mirror([_card(A)], **_kw(tmp_path, reg))
    out = render_image_mirror_report(rep)
    assert "source_missing" in out and A in out


def test_select_image_cards_splits_non_img():
    rows = [
        {"card_id": "i1", "asset_type": "IMG"},
        {"card_id": "p1", "asset_type": "PDF"},
        {"card_id": "v1", "asset_type": "VID"},
    ]
    in_scope, skipped = select_image_cards(["i1", "p1", "v1"], rows)
    assert in_scope == ["i1"]
    assert skipped == {"p1": "PDF", "v1": "VID"}


# --- results are per row --------------------------------------------------


def test_two_rows_of_one_card_both_reported(tmp_path):
    reg = _registry(tmp_path / "reg.jsonl", (A, JPG_SHA, f"archive/{JPG_SHA}.jpg"))
    _put(tmp_path / "images", A, "p.jpg", JPG)
    cards = [_card(A, "p.jpg"), _card(A, "gone.jpg")]
    rep = run_image_mirror(cards, **_kw(tmp_path, reg))
    assert len(rep.results) == 2
    assert rep.ok
    assert rep.counts["mirrored"] == 1 and rep.counts["already_present"] == 1
    pf = verify_image_mirror(
        [_card(A), _card(A)], mirror_root=tmp_path / "r2-mirror", registry_path=reg
    )
    assert pf.ok
