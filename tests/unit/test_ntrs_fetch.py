"""NTRS fetcher: one endpoint, pinned host, courteous, aborts on any non-2xx.

Fixture-driven: no socket, no real waiting.
"""

from __future__ import annotations

import pytest

from pursue_index.ntrs_fetch import (
    NTRS_HOSTS_PATH,
    USER_AGENT,
    NtrsFetchError,
    search_url,
)
from pursue_index.ntrs_source import run_searches
from pursue_index.source_hosts import load_source_hosts
from tests.support.ntrs_fakes import HOSTS, REPO, TODAY, Net, Resp, card

_SEARCH = "https://ntrs.nasa.gov/api/citations/search?q=Apollo+12+Medical+Debriefing&page.size=5"


def test_hosts_file_lists_only_ntrs() -> None:
    assert load_source_hosts(REPO / NTRS_HOSTS_PATH) == HOSTS


def test_search_url_is_the_one_search_endpoint() -> None:
    assert search_url("Apollo 12 Medical Debriefing") == _SEARCH


def test_only_the_search_path_is_requested() -> None:
    net = Net()
    net.fetcher().search("Apollo 12 Medical Debriefing")
    assert net.urls == [_SEARCH]


@pytest.mark.parametrize(
    "url",
    [
        "https://ntrs.nasa.gov/api/citations/20260006073/downloads",
        "https://ntrs.nasa.gov/api/citations/20260006073/downloads/file.pdf",
        "https://ntrs.nasa.gov/api/citations/search/extra?q=x",
        "https://ntrs.nasa.gov/citations/20260006073",
        "https://ntrs.nasa.gov/api/citations/search.pdf?q=x",
        "https://ntrs.nasa.gov/files/report.pdf",
        "https://ntrs.nasa.gov/api/citations/search/../20260006073/downloads",
    ],
)
def test_other_paths_are_refused_before_any_request(url: str) -> None:
    net = Net()
    with pytest.raises(NtrsFetchError):
        net.fetcher().fetch(url)
    assert net.events == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/citations/search?q=x",
        "https://ntrs.nasa.gov.evil.example/api/citations/search?q=x",
        "https://sub.ntrs.nasa.gov/api/citations/search?q=x",
        "http://ntrs.nasa.gov/api/citations/search?q=x",
        "ftp://ntrs.nasa.gov/api/citations/search?q=x",
    ],
)
def test_off_list_host_and_plain_http_are_refused(url: str) -> None:
    net = Net()
    with pytest.raises(NtrsFetchError):
        net.fetcher().fetch(url)
    assert net.events == []


def test_one_second_sleep_comes_before_every_request() -> None:
    net = Net()
    fetcher = net.fetcher()
    fetcher.search("one")
    fetcher.search("two")
    assert net.events == ["sleep:1.0", "get", "sleep:1.0", "get"]


def test_generic_user_agent_is_sent() -> None:
    net = Net()
    net.fetcher().search("x")
    assert USER_AGENT == "pursue-index-provenance/1.0 (metadata search only)"
    assert net.headers[0]["User-Agent"] == USER_AGENT


@pytest.mark.parametrize("status", [403, 429, 500, 301, 404])
def test_a_non_2xx_aborts_with_no_further_request(status: int) -> None:
    net = Net(Resp(status))
    manifest = {"cards": [card(card_id="a"), card(card_id="b"), card(card_id="c")]}
    with pytest.raises(NtrsFetchError):
        run_searches(manifest, net.fetcher(), TODAY)
    assert net.events.count("get") == 1


def test_request_and_status_counts_are_kept() -> None:
    net = Net(Resp(200, {"results": []}), Resp(200, {"results": []}), Resp(429))
    fetcher = net.fetcher()
    fetcher.search("a")
    fetcher.search("b")
    with pytest.raises(NtrsFetchError):
        fetcher.search("c")
    assert fetcher.fetch_counts() == {"requests": 3, "status_counts": {"200": 2, "429": 1}}
