"""A card with several assets (a PDF plus a video) compares each asset only to its own rows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.r2_verify_harness import NEW_BODY, OLD_BODY, World, r2, sha

import _r2_fetch  # noqa: E402  (scripts/ is on sys.path via the harness)
import _r2_run_state  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
VIDEO_URL = "https://www.dvidshub.net/video/1006056"
VIDEO_BODY = b"video bytes, quite different"


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _two_asset_world(w: World, *, pdf_body: bytes) -> str:
    """PDF row, then a newer DVIDS row, for one card; upstream serves ``pdf_body`` for the PDF."""
    cid = w.add_card(1, prior=OLD_BODY, body=pdf_body, head_matches_prior=False)
    w.rows.append({
        **w.rows[0], "asset_url": VIDEO_URL, "asset_filename": "1006056.mp4",
        "byte_sha256": sha(VIDEO_BODY), "byte_size": len(VIDEO_BODY), "upstream_etag": '"v1"',
        "archive_key": f"archive/{sha(VIDEO_BODY)}.mp4", "current_key": f"{cid}.mp4",
        "fetched_at": "2026-06-01T00:00:00+00:00",
    })
    return cid


_FULL = ("--full-hash", "--max-bytes-per-run", "1000", "--fail-on-drift")


def _args(w: World) -> tuple[str, ...]:
    return (*_FULL, "--run-record", str(w.record), "--dispositions", str(w.dispositions))


def test_the_pdf_is_unchanged_when_a_newer_row_belongs_to_the_video(w, capsys):
    _two_asset_world(w, pdf_body=OLD_BODY)
    assert w.run(*_args(w)) == 0
    assert w.new_rows() == []
    assert "BYTE DRIFT" not in capsys.readouterr().err


def test_a_changed_pdf_is_drift_against_the_pdf_row(w, capsys):
    cid = _two_asset_world(w, pdf_body=NEW_BODY)
    assert w.run(*_args(w)) != 0
    err = capsys.readouterr().err
    assert f"{cid} old sha {sha(OLD_BODY)} -> new sha {sha(NEW_BODY)}" in err


def test_a_url_with_no_prior_row_is_net_new_not_drift(w, capsys):
    w.add_card(1, prior=None, body=NEW_BODY)
    w.rows.append({
        "card_id": w.cards[0]["card_id"], "asset_url": VIDEO_URL, "asset_filename": "v.mp4",
        "byte_sha256": sha(VIDEO_BODY), "byte_size": 3, "upstream_etag": None,
        "archive_key": "a", "current_key": "b", "fetched_at": "2026-06-01T00:00:00+00:00",
    })
    assert w.run(*_args(w)) == 0
    assert len(w.new_rows()) == 1
    assert "BYTE DRIFT" not in capsys.readouterr().err


def test_the_head_shortcut_uses_the_pdf_rows_size_and_etag(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY)  # HEAD agrees with the PDF row
    _two_asset_world_tail(w)
    assert w.run() == 0
    assert w.fetched == []  # head-unchanged against the PDF row, not the newer video row


def _two_asset_world_tail(w: World) -> None:
    w.rows.append({
        **w.rows[0], "asset_url": VIDEO_URL, "byte_sha256": sha(VIDEO_BODY),
        "byte_size": len(VIDEO_BODY), "upstream_etag": '"v1"',
        "fetched_at": "2026-06-01T00:00:00+00:00",
    })


def test_the_budget_estimate_uses_the_pdf_rows_size(w):
    w.add_card(1, prior=OLD_BODY, body=OLD_BODY, head_matches_prior=False)
    _two_asset_world_tail(w)
    # PDF is 9 B, the video row 28 B: a 20 B budget fits the PDF only if sized per asset.
    assert w.run("--full-hash", "--max-bytes-per-run", "20", "--run-record", str(w.record)) == 0
    assert w.fetched == [w.cards[0]["asset_url"]]


def _row(cid, url, digest, when):
    return {"card_id": cid, "asset_url": url, "byte_sha256": digest, "fetched_at": when}


SINCE = datetime.fromisoformat("2026-01-01T00:00:00+00:00")


def test_a_pdf_row_then_a_video_row_in_the_window_is_not_drift():
    reg = {"c": [_row("c", "https://x/a.pdf", "a" * 64, "2026-05-01T00:00:00+00:00"),
                 _row("c", VIDEO_URL, "b" * 64, "2026-06-01T00:00:00+00:00")]}
    assert _r2_run_state.registry_drift_since(reg, SINCE) == []


def test_two_pdf_rows_with_different_shas_are_drift():
    u = "https://x/a.pdf"
    reg = {"c": [_row("c", u, "a" * 64, "2026-05-01T00:00:00+00:00"),
                 _row("c", VIDEO_URL, "b" * 64, "2026-05-15T00:00:00+00:00"),
                 _row("c", u, "d" * 64, "2026-06-01T00:00:00+00:00")]}
    assert _r2_run_state.registry_drift_since(reg, SINCE) == [("c", "a" * 64, "d" * 64)]


# 9 observed fetches: (card_id, sha of the manifest PDF as fetched).
OBSERVED = [
    ("c1c59236394f7b14", "f9deed9063306b0c45a5a0f6b754db6967f7dc3a0ed66097f154be4b0f033399"),
    ("43db2719407a7897", "1822564fbae08f152ad4541c8d067a6ec3b6014c4b4eb8209604e1facb5e1bb3"),
    ("4555d94dd6067f57", "b3b3f023d70bcce3178de9fe6a019ea6db5e5145bc7e28a49308442e190ef817"),
    ("9961adf6adf1010b", "4752dd830144b21c3055a2fea8b44c551445b41622c27db64fb0fa07c2dcd93d"),
    ("d8e5687dc870892d", "ea1cd5296143f378db533066b524c32c1ecfbfd43d74ec6be7d832c20fa271bb"),
    ("ea029a05470b8f4e", "fd4deb1e48fcfa7fd2370b6459877882e6d6fdd0226ecaa881a45fba690172df"),
    ("3746998b8c506e5c", "7078d96f334dbf396e0e0a141f943009fe2191cd20842e16ee381bcbc2776c43"),
    ("c788c17e8cc32230", "b4f4f4ce6dc7687a543905990671f999cd6c5a9e579159bfda501bf6d04f4445"),
    ("88a20bf256ccce7a", "90b353682ba2181149054d0911b7553e58e959438dd4de531a06fc387a332f85"),
]


def test_replaying_the_nine_observed_fetches_against_the_real_data_reports_no_drift(
    tmp_path, monkeypatch, capsys
):
    registry = r2.load_registry(_REPO / "data" / "asset-bytes-registry.jsonl")
    cards = {c["card_id"]: c for c in json.loads(
        (_REPO / "data" / "manifests" / "latest.json").read_text())["cards"]
        if c["asset_type"] == "PDF"}
    drift = []
    for cid, digest in OBSERVED:
        m = cards[cid]
        assert m["asset_type"] == "PDF"
        card = SimpleNamespace(card_id=cid, asset_url=m["asset_url"],
                               asset_filename=m["asset_filename"], asset_type="PDF")
        monkeypatch.setattr(r2, "head_asset", lambda u: (None, None, None))
        monkeypatch.setattr(r2, "fetch_asset", lambda u, d, _s=digest: (_s, 1))
        state = r2.RunState()
        state.full_hash = True
        result = r2._process_card(card, registry, object(), "b", True, tmp_path / "r.jsonl", state)
        drift += state.drift
        assert result in ("unchanged", "new"), (cid, result)
    assert drift == []
