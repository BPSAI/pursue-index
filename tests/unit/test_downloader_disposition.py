"""UBV round 3: a stale registry row fails with guidance, unless a disposition covers it."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from pursue_index.byte_dispositions import Disposition
from pursue_index.config.settings import Settings
from pursue_index.download.downloader import DownloadBatchError, download_all
from pursue_index.scrape.types import CardMetadata

OLD, NEW = b"stale registry bytes", b"legitimately re-saved bytes"
OLD_SHA, NEW_SHA = hashlib.sha256(OLD).hexdigest(), hashlib.sha256(NEW).hexdigest()
CID = "abc1234567890def"


def _card() -> CardMetadata:
    return CardMetadata.model_construct(
        card_id=CID, title="t", asset_type="PDF", agency="A", redacted=False,
        asset_url="https://www.war.gov/x.pdf", asset_filename="x.pdf",
    )


def _disp(old=OLD_SHA, new=NEW_SHA, kind="resave-content-verified") -> dict:
    return {(CID, new): Disposition(CID, old, new, kind, "2026-11-21", "re-save", "3" * 64, old)}


@pytest.fixture
def served(tmp_path, monkeypatch):
    from tenacity import wait_none

    import pursue_index.download.downloader as dl

    monkeypatch.setattr(Settings, "pdf_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(dl._download_one.retry, "wait", wait_none())
    real = httpx.AsyncClient
    monkeypatch.setattr(
        dl.httpx, "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=NEW)), **kw),
    )
    return tmp_path


async def _run(dispositions, outcomes=None):
    return await download_all(
        type("M", (), {"cards": [_card()]})(), registry_shas={CID: OLD_SHA},
        outcomes=outcomes, dispositions=dispositions,
    )


async def test_a_mismatch_with_no_disposition_fails_and_says_what_to_do(served):
    with pytest.raises(DownloadBatchError) as err:
        await _run({})
    msg = err.value.failed[CID]
    assert CID in msg and OLD_SHA in msg and NEW_SHA in msg
    assert "byte-change-dispositions.jsonl" in msg and "resave-content-verified" in msg
    assert not (served / CID / "x.pdf").exists()


async def test_a_mismatch_covered_by_a_matching_disposition_passes(served):
    outcomes: dict[str, str] = {}
    results = await _run(_disp(), outcomes)
    assert results[0] is not None and results[0].read_bytes() == NEW
    assert outcomes == {CID: "dispositioned-resave"}


async def test_a_disposition_for_a_different_new_sha_still_fails(served):
    with pytest.raises(DownloadBatchError):
        await _run(_disp(new="9" * 64))


async def test_a_disposition_over_a_different_old_sha_still_fails(served):
    with pytest.raises(DownloadBatchError):
        await _run(_disp(old="8" * 64))


async def test_a_content_changed_disposition_does_not_cover(served):
    with pytest.raises(DownloadBatchError):
        await _run(_disp(kind="content-changed"))
