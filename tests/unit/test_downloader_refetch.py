"""A bytes-changed card is re-fetched, verified against the registry, then replaced."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from pursue_index.cli.worklist import read_worklist_reasons
from pursue_index.config.settings import Settings
from pursue_index.download.downloader import (
    DownloadShaMismatchError,
    _download_one,
    download_all,
)
from pursue_index.scrape.types import CardMetadata

OLD, NEW = b"old pdf bytes", b"new pdf bytes"
NEW_SHA = hashlib.sha256(NEW).hexdigest()
URL = "https://www.war.gov/x.pdf"


def _card() -> CardMetadata:
    return CardMetadata.model_construct(
        card_id="abc1234567890def", title="t", asset_type="PDF", agency="A", redacted=False,
        asset_url=URL, asset_filename="x.pdf",
    )


@pytest.fixture
def target(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "pdf_dir", property(lambda self: tmp_path))
    path = tmp_path / "abc1234567890def" / "x.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(OLD)
    return path


def _client(content: bytes, calls: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=content)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_bytes_changed_card_is_refetched_and_replaced(target):
    calls: list[str] = []
    async with _client(NEW, calls) as client:
        result = await _download_one(client, _card(), expected_sha=NEW_SHA)
    assert calls == [URL]
    assert result == target
    assert hashlib.sha256(target.read_bytes()).hexdigest() == NEW_SHA
    assert [p.name for p in target.parent.iterdir()] == ["x.pdf"]  # no temp file left


async def test_sha_mismatch_keeps_old_file_and_raises(target):
    calls: list[str] = []
    async with _client(b"something else", calls) as client:
        with pytest.raises(DownloadShaMismatchError):
            await _download_one(client, _card(), expected_sha=NEW_SHA)
    assert len(calls) == 1, "a sha mismatch is not retried"
    assert target.read_bytes() == OLD
    assert [p.name for p in target.parent.iterdir()] == ["x.pdf"]


async def test_unchanged_card_with_existing_file_is_skipped(target):
    calls: list[str] = []
    async with _client(NEW, calls) as client:
        result = await _download_one(client, _card())
    assert result == target
    assert calls == []
    assert target.read_bytes() == OLD


async def test_download_all_refetches_only_the_refresh_cards(target, monkeypatch):
    import pursue_index.download.downloader as dl

    seen: list[tuple[str, str | None]] = []

    async def fake(client, card, *, expected_sha=None):
        seen.append((card.card_id, expected_sha))

    monkeypatch.setattr(dl, "_download_one", fake)
    manifest = type("M", (), {"cards": [_card()]})()
    await download_all(manifest, refresh_shas={"abc1234567890def": NEW_SHA})
    assert seen == [("abc1234567890def", NEW_SHA)]


def test_read_worklist_reasons(tmp_path):
    wl = tmp_path / "w.txt"
    wl.write_text("# tranche: x\nabc1234567890def\tbytes-changed\n1111111111111111\tnew\n2222222222222222\n")
    assert read_worklist_reasons(wl) == {
        "abc1234567890def": "bytes-changed", "1111111111111111": "new", "2222222222222222": "",
    }


def test_download_cli_maps_bytes_changed_cards_to_registry_sha(tmp_path, monkeypatch):
    import json

    import pursue_index.paths as paths
    from pursue_index.cli.download_ocr_cli import _bytes_changed_shas

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "asset-bytes-registry.jsonl").write_text(
        json.dumps({"card_id": "abc1234567890def", "byte_sha256": NEW_SHA,
                    "current_key": "abc1234567890def.pdf"}) + "\n"
    )
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    wl = tmp_path / "w.txt"
    wl.write_text("# tranche: x\nabc1234567890def\tbytes-changed\n1111111111111111\tnew\n")
    assert _bytes_changed_shas(wl) == {"abc1234567890def": NEW_SHA}
    assert _bytes_changed_shas(None) == {}
