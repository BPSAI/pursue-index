"""The poll lane fetches only what it should, and only so much of it.

URLs come from an upstream CSV and from ``field_changes`` values, and card ids
from the same place; none of it is trusted. Every fetched URL passes one
validator (https, the official host, no userinfo, port 443, no literal IP) and
no redirect leaves that allowlist. A rejected target is a logged skip, never an
exception that aborts the poll. Downloads are bounded in bytes, in time and in
count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pursue_index.scrape import csv_fetcher, pdf_pages
from pursue_index.scrape.pdf_pages import PageTarget, fetch_and_count, page_targets
from pursue_index.scrape.pdf_urls import is_allowed_pdf_url
from pursue_index.scrape.poll_snapshot import SnapshotDiffResult
from pursue_index.scrape.types import CardMetadata
from tests.support.pdf_page_fakes import FakeHttpGet, pdf_bytes

_BASE = "https://www.war.gov/medialink/ufo"
_OK_ID = "00000000000000aa"
_OK_URL = f"{_BASE}/a.pdf"


@pytest.mark.parametrize("url", [
    _OK_URL,
    "https://WWW.WAR.GOV/medialink/a.pdf",
    "https://www.war.gov:443/medialink/a.pdf",
    "https://www.war.gov/medialink/a.pdf?x=1",
])
def test_allowed_urls(url: str) -> None:
    assert is_allowed_pdf_url(url)


@pytest.mark.parametrize("url", [
    "http://www.war.gov/a.pdf",
    "ftp://www.war.gov/a.pdf",
    "file:///etc/passwd.pdf",
    "https://evil.example/a.pdf",
    "https://www.war.gov.evil.example/a.pdf",
    "https://www.war.gov@evil.example/a.pdf",
    "https://user:pw@www.war.gov/a.pdf",
    "https://www.war.gov:8443/a.pdf",
    "https://www.war.gov:80/a.pdf",
    "https://169.254.169.254/a.pdf",
    "https://10.0.0.1/a.pdf",
    "https://[::1]/a.pdf",
    "https://2130706433/a.pdf",
    "https://www.war.gov\\@evil.example/a.pdf",
    "https://www.war.gov/a b.pdf",
    "https://www.war.gov./a.pdf",
    "//www.war.gov/a.pdf",
    "/medialink/a.pdf",
    "",
])
def test_rejected_urls(url: str) -> None:
    assert not is_allowed_pdf_url(url)


def _card(card_id: str, url: str) -> CardMetadata:
    return CardMetadata(card_id=card_id, title="t", asset_type="PDF",
                        agency="FBI", asset_url=url)


def _diff(added=(), field_changes=()) -> SnapshotDiffResult:
    return SnapshotDiffResult(added=list(added), removed=[],
                              field_changes=list(field_changes), new_columns=[])


def test_page_targets_skips_off_allowlist_urls_without_raising() -> None:
    diff = _diff(
        added=[_card(_OK_ID, _OK_URL),
               _card("00000000000000bb", "https://169.254.169.254/x.pdf")],
        field_changes=[{"card_id": "00000000000000cc", "diffs": [
            {"field": "asset_url", "old": "", "new": "https://evil.example/y.pdf"}]}],
    )
    assert page_targets(diff) == [PageTarget(_OK_ID, _OK_URL)]


@pytest.mark.parametrize("bad", [
    "../../etc/cron.d/x", "card001", "00000000000000AA", "00000000000000a", "",
    "0000000000000000a", "..", "a/b",
])
def test_page_targets_skips_invalid_card_ids(bad: str) -> None:
    diff = _diff(
        added=[_card(bad, _OK_URL), _card(_OK_ID, _OK_URL)],
        field_changes=[{"card_id": bad, "diffs": [
            {"field": "asset_url", "old": "", "new": f"{_BASE}/m.pdf"}]}],
    )
    assert page_targets(diff) == [PageTarget(_OK_ID, _OK_URL)]


def test_fetch_and_count_never_fetches_or_writes_for_a_hostile_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeHttpGet(bodies={_OK_URL: pdf_bytes(1)})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    hostile = [PageTarget("../../escape", _OK_URL),
               PageTarget(_OK_ID, "https://169.254.169.254/a.pdf")]
    with fetch_and_count(hostile) as fetched:
        assert fetched.page_counts == {}
        assert not list(fetched.workdir.iterdir())
    assert fake.calls == []
    assert not (tmp_path.parent / "escape.pdf").exists()


def test_redirects_are_not_followed_by_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHttpGet(bodies={_OK_URL: pdf_bytes(1)})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]):
        pass
    assert fake.calls[0][1]["allow_redirects"] is False


def test_a_redirect_off_the_allowlist_is_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    internal = "http://169.254.169.254/latest/meta-data.pdf"
    fake = FakeHttpGet(bodies={internal: pdf_bytes(1)}, redirects={_OK_URL: internal})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]) as fetched:
        assert fetched.fallback_card_ids == [_OK_ID]
    assert [u for u, _ in fake.calls] == [_OK_URL]


def test_a_redirect_within_the_allowlist_is_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moved = f"{_BASE}/moved.pdf"
    fake = FakeHttpGet(bodies={moved: pdf_bytes(3)}, redirects={_OK_URL: moved})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]) as fetched:
        assert fetched.page_counts == {_OK_ID: 3}
    assert [u for u, _ in fake.calls] == [_OK_URL, moved]


def test_a_redirect_loop_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    other = f"{_BASE}/b.pdf"
    fake = FakeHttpGet(bodies={}, redirects={_OK_URL: other, other: _OK_URL})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]) as fetched:
        assert fetched.fallback_card_ids == [_OK_ID]
    assert len(fake.calls) <= 5


def test_an_oversized_body_is_abandoned_mid_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_pages, "_MAX_PDF_BYTES", 2_000)
    big = pdf_bytes(1) + b"\0" * 200_000
    fake = FakeHttpGet(bodies={_OK_URL: big})
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]) as fetched:
        assert fetched.fallback_card_ids == [_OK_ID]
        assert not list(fetched.workdir.iterdir())
    resp = fake.responses[0]
    assert resp.consumed < len(big) and resp.closed


def test_a_body_at_the_limit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    body = pdf_bytes(2)
    monkeypatch.setattr(pdf_pages, "_MAX_PDF_BYTES", len(body))
    monkeypatch.setattr(csv_fetcher, "http_get", FakeHttpGet(bodies={_OK_URL: body}))
    with fetch_and_count([PageTarget(_OK_ID, _OK_URL)]) as fetched:
        assert fetched.page_counts == {_OK_ID: 2}


def _many(n: int) -> tuple[list[PageTarget], FakeHttpGet]:
    targets = [PageTarget(f"{i:016x}", f"{_BASE}/{i}.pdf") for i in range(n)]
    return targets, FakeHttpGet(bodies={t.url: pdf_bytes(1) for t in targets})


def test_targets_past_the_count_limit_fall_back_unfetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_pages, "_MAX_TARGETS", 2)
    targets, fake = _many(4)
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count(targets) as fetched:
        assert sorted(fetched.page_counts) == [targets[0].card_id, targets[1].card_id]
        assert fetched.fallback_card_ids == [targets[2].card_id, targets[3].card_id]
    assert len(fake.calls) == 2


def test_targets_past_the_time_budget_fall_back_unfetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(pdf_pages, "_monotonic", lambda: next(clock))
    monkeypatch.setattr(pdf_pages, "_TOTAL_BUDGET_S", 50.0)
    targets, fake = _many(3)
    monkeypatch.setattr(csv_fetcher, "http_get", fake)
    with fetch_and_count(targets) as fetched:
        assert list(fetched.page_counts) == [targets[0].card_id]
        assert fetched.fallback_card_ids == [targets[1].card_id, targets[2].card_id]
    assert len(fake.calls) == 1
