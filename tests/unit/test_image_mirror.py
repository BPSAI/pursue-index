"""NAS r2-mirror stage for IMG cards: images/<card>/<file> -> archive/<sha>.<ext>."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pursue_index.cli import storage_cli
from pursue_index.cli.commands import app
from pursue_index.release.image_mirror import (
    render_image_mirror_report,
    render_image_verify,
    run_image_mirror,
    select_image_cards,
    verify_image_mirror,
)
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
    assert not pf.ok and list(pf.details) == [b]
    assert b in render_image_verify(pf)
    (_archive(tmp_path) / f"{PNG_SHA}.png").write_bytes(b"wrong")
    pf = verify_image_mirror(cards, **kw)
    assert not pf.ok and list(pf.details) == [b]
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
