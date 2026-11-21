"""A bytes-changed card is re-fetched, verified against the registry, then replaced."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from pursue_index.cli.worklist import read_worklist_reasons
from pursue_index.config.settings import Settings
from pursue_index.download.downloader import (
    DownloadBatchError,
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


def _card_named(card_id: str) -> CardMetadata:
    card = _card()
    return card.model_copy(update={"card_id": card_id, "asset_filename": f"{card_id}.pdf"})


async def test_one_sha_mismatch_does_not_abort_the_other_cards(tmp_path, monkeypatch):
    import pursue_index.download.downloader as dl

    monkeypatch.setattr(Settings, "pdf_dir", property(lambda self: tmp_path))
    bad, good = _card_named("bad1234567890def"), _card_named("good234567890def")
    paths = {c.card_id: tmp_path / c.card_id / c.asset_filename for c in (bad, good)}
    for path in paths.values():
        path.parent.mkdir(parents=True)
        path.write_bytes(OLD)
    served = {bad.card_id: b"not what the registry has", good.card_id: NEW}

    async def fake_one(client, card, *, expected_sha=None):
        data = served[card.card_id]
        if hashlib.sha256(data).hexdigest() != expected_sha:
            raise DownloadShaMismatchError(f"card {card.card_id}: mismatch")
        paths[card.card_id].write_bytes(data)
        return paths[card.card_id]

    monkeypatch.setattr(dl, "_download_one", fake_one)
    manifest = type("M", (), {"cards": [bad, good]})()
    with pytest.raises(DownloadBatchError) as err:
        await download_all(
            manifest, refresh_shas={bad.card_id: NEW_SHA, good.card_id: NEW_SHA}
        )
    assert paths[good.card_id].read_bytes() == NEW, "the healthy card still refreshed"
    assert paths[bad.card_id].read_bytes() == OLD, "the failed card keeps its old file"
    assert list(err.value.failed) == [bad.card_id]
    assert bad.card_id in str(err.value) and good.card_id not in str(err.value)


async def test_every_failed_card_is_named(monkeypatch):
    import pursue_index.download.downloader as dl

    async def fake_one(client, card, *, expected_sha=None):
        raise DownloadShaMismatchError(f"card {card.card_id}: mismatch")

    monkeypatch.setattr(dl, "_download_one", fake_one)
    cards = [_card_named("aaaa234567890def"), _card_named("bbbb234567890def")]
    with pytest.raises(DownloadBatchError) as err:
        await download_all(type("M", (), {"cards": cards})(), refresh_shas={})
    assert sorted(err.value.failed) == ["aaaa234567890def", "bbbb234567890def"]


# ---- non-refresh downloads verify their sha; every failure joins the batch ----


@pytest.fixture
def no_retry_wait(monkeypatch):
    from tenacity import wait_none

    from pursue_index.download.downloader import _download_one as fn

    monkeypatch.setattr(fn.retry, "wait", wait_none())


@pytest.fixture
def empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "pdf_dir", property(lambda self: tmp_path))
    return tmp_path


async def test_fresh_download_with_wrong_sha_is_not_kept(empty_dir):
    calls: list[str] = []
    async with _client(b"not what the registry has", calls) as client:
        with pytest.raises(DownloadShaMismatchError):
            await _download_one(client, _card(), registry_sha=NEW_SHA)
    assert not (empty_dir / "abc1234567890def" / "x.pdf").exists()
    assert [p.name for p in (empty_dir / "abc1234567890def").iterdir()] == []


async def test_fresh_download_with_matching_registry_sha_is_kept(empty_dir):
    async with _client(NEW, []) as client:
        result = await _download_one(client, _card(), registry_sha=NEW_SHA)
    assert result is not None and result.read_bytes() == NEW


async def test_fresh_download_with_no_registry_row_is_unchecked(empty_dir):
    async with _client(NEW, []) as client:
        result = await _download_one(client, _card())
    assert result is not None and result.read_bytes() == NEW


async def test_existing_file_is_still_skipped_when_a_registry_sha_is_known(target):
    calls: list[str] = []
    async with _client(NEW, calls) as client:
        result = await _download_one(client, _card(), registry_sha=NEW_SHA)
    assert result == target and calls == [] and target.read_bytes() == OLD


async def test_download_all_passes_the_registry_sha_only_to_pdf_cards(monkeypatch):
    import pursue_index.download.downloader as dl

    seen: dict[str, dict] = {}

    async def fake(client, card, **kw):
        seen[card.card_id] = kw

    monkeypatch.setattr(dl, "_download_one", fake)
    img = _card_named("img1234567890def").model_copy(update={"asset_type": "IMG"})
    pdf = _card_named("pdf1234567890def")
    manifest = type("M", (), {"cards": [img, pdf]})()
    await download_all(
        manifest, registry_shas={img.card_id: NEW_SHA, pdf.card_id: NEW_SHA}
    )
    assert seen[pdf.card_id] == {"registry_sha": NEW_SHA}
    assert seen[img.card_id] == {}


async def test_http_status_error_joins_the_batch_and_the_rest_finish(
    empty_dir, monkeypatch, no_retry_wait
):
    import pursue_index.download.downloader as dl

    bad, good = _card_named("bad1234567890def"), _card_named("good234567890def")

    def handler(request: httpx.Request) -> httpx.Response:
        if "bad1234567890def" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, content=NEW)

    bad = bad.model_copy(update={"asset_url": "https://www.war.gov/bad1234567890def.pdf"})
    good = good.model_copy(update={"asset_url": "https://www.war.gov/good234567890def.pdf"})
    real = httpx.AsyncClient
    monkeypatch.setattr(
        dl.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(DownloadBatchError) as err:
        await download_all(type("M", (), {"cards": [bad, good]})())
    assert list(err.value.failed) == [bad.card_id]
    assert "503" in err.value.failed[bad.card_id]
    assert (empty_dir / good.card_id / good.asset_filename).read_bytes() == NEW


async def test_network_error_joins_the_batch(empty_dir, monkeypatch, no_retry_wait):
    import pursue_index.download.downloader as dl

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        dl.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(DownloadBatchError) as err:
        await download_all(type("M", (), {"cards": [_card()]})())
    assert "abc1234567890def" in err.value.failed and "boom" in err.value.failed["abc1234567890def"]


async def test_write_error_joins_the_batch(monkeypatch, tmp_path, no_retry_wait):
    import pursue_index.download.downloader as dl

    # pdf_dir is a file, so creating the card's directory fails with OSError.
    blocker = tmp_path / "blocked"
    blocker.write_text("x")
    monkeypatch.setattr(Settings, "pdf_dir", property(lambda self: blocker))
    real = httpx.AsyncClient
    monkeypatch.setattr(
        dl.httpx, "AsyncClient",
        lambda **kw: real(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=NEW)), **kw
        ),
    )
    with pytest.raises(DownloadBatchError) as err:
        await download_all(type("M", (), {"cards": [_card()]})())
    assert list(err.value.failed) == ["abc1234567890def"]


def test_download_cli_exits_non_zero_naming_each_card(monkeypatch):
    from typer.testing import CliRunner

    import pursue_index.cli.download_ocr_cli as cli
    import pursue_index.download.downloader as dl

    async def boom(manifest, **kw):
        raise DownloadBatchError({"aaaa234567890def": "503", "bbbb234567890def": "timeout"})

    monkeypatch.setattr(dl, "download_all", boom)
    monkeypatch.setattr(cli, "_scoped_manifest", lambda m, w: object())
    monkeypatch.setattr(cli, "_registry_shas", lambda: {})
    monkeypatch.setattr(cli.settings, "ensure_dirs", lambda: None)
    result = CliRunner().invoke(cli.download_app, ["run"])
    assert result.exit_code == 1
    out = result.output
    assert "aaaa234567890def" in out and "bbbb234567890def" in out
