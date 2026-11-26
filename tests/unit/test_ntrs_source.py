"""NASA NTRS metadata source: fetch rules, title matching, dated claims, report wiring.

Fixture-driven: no socket, no real waiting. The one real response is
``tests/fixtures/ntrs-search-apollo12-debrief.json``.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pursue_index import ntrs_source
from pursue_index.ntrs_fetch import (
    NTRS_HOSTS_PATH,
    USER_AGENT,
    NtrsFetchError,
    NtrsFetcher,
    search_url,
)
from pursue_index.ntrs_source import (
    MATCH_THRESHOLD,
    RESULT_CLAIM,
    RESULT_NO_COPY,
    RESULT_POST_DATING,
    build_output,
    evaluate_card,
    normalize_query,
    run_searches,
    title_matches,
    unresolved_nasa_cards,
)
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import RESOLVED_BY_CLAIM, UNRESOLVED, build_report
from pursue_index.resolved_claim import ResolutionSource
from pursue_index.source_hosts import load_source_hosts

_REPO = Path(__file__).resolve().parents[2]
_SAMPLE = _REPO / "tests" / "fixtures" / "ntrs-search-apollo12-debrief.json"
_TODAY = date(2026, 11, 25)
_HOSTS = frozenset({"ntrs.nasa.gov"})
_SEARCH = "https://ntrs.nasa.gov/api/citations/search?q=Apollo+12+Medical+Debriefing&page.size=5"


def _sample() -> dict[str, Any]:
    return json.loads(_SAMPLE.read_text())


def _card(**over: Any) -> dict[str, Any]:
    card = {
        "card_id": "c-apollo12",
        "title": "NASA-UAP-D099, Apollo 12 Medical Debriefing",
        "agency": "NASA",
        "release_date": "5/8/2026",
        "incident_date": "1969",
        "description": "",
        "asset_filename": "NASA-UAP-D099.pdf",
    }
    card.update(over)
    return card


def _variant(**fields: Any) -> dict[str, Any]:
    """The real sample with top-level result fields replaced (None removes one)."""
    data = copy.deepcopy(_sample())
    for key, value in fields.items():
        if value is None:
            data["results"][0].pop(key, None)
        else:
            data["results"][0][key] = value
    return data


class _Resp:
    def __init__(self, status: int, payload: Any = None) -> None:
        self.status_code = status
        self.text = json.dumps(payload if payload is not None else {})
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        return json.loads(self.text)


class _Net:
    """Records events in order; replies from a queue, repeating the last."""

    def __init__(self, *responses: _Resp) -> None:
        self.responses = list(responses) or [_Resp(200, {"results": []})]
        self.events: list[str] = []
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, headers: Any) -> _Resp:
        self.events.append("get")
        self.urls.append(url)
        self.headers.append(dict(headers))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def sleep(self, seconds: float) -> None:
        self.events.append(f"sleep:{seconds}")

    def fetcher(self) -> NtrsFetcher:
        return NtrsFetcher(get=self.get, hosts=_HOSTS, sleep=self.sleep)


# --- fetch rules -------------------------------------------------------------


def test_hosts_file_lists_only_ntrs() -> None:
    assert load_source_hosts(_REPO / NTRS_HOSTS_PATH) == _HOSTS


def test_search_url_is_the_one_search_endpoint() -> None:
    assert search_url("Apollo 12 Medical Debriefing") == _SEARCH


def test_only_the_search_path_is_requested() -> None:
    net = _Net()
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
    net = _Net()
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
    net = _Net()
    with pytest.raises(NtrsFetchError):
        net.fetcher().fetch(url)
    assert net.events == []


def test_one_second_sleep_comes_before_every_request() -> None:
    net = _Net()
    fetcher = net.fetcher()
    fetcher.search("one")
    fetcher.search("two")
    assert net.events == ["sleep:1.0", "get", "sleep:1.0", "get"]


def test_generic_user_agent_is_sent() -> None:
    net = _Net()
    net.fetcher().search("x")
    assert USER_AGENT == "pursue-index-provenance/1.0 (metadata search only)"
    assert net.headers[0]["User-Agent"] == USER_AGENT


@pytest.mark.parametrize("status", [403, 429, 500, 301, 404])
def test_a_non_2xx_aborts_with_no_further_request(status: int) -> None:
    net = _Net(_Resp(status))
    manifest = {"cards": [_card(card_id="a"), _card(card_id="b"), _card(card_id="c")]}
    with pytest.raises(NtrsFetchError):
        run_searches(manifest, net.fetcher(), _TODAY)
    assert net.events.count("get") == 1


def test_request_and_status_counts_are_kept() -> None:
    net = _Net(_Resp(200, {"results": []}), _Resp(200, {"results": []}), _Resp(429))
    fetcher = net.fetcher()
    fetcher.search("a")
    fetcher.search("b")
    with pytest.raises(NtrsFetchError):
        fetcher.search("c")
    assert fetcher.fetch_counts() == {"requests": 3, "status_counts": {"200": 2, "429": 1}}


# --- selection and query -----------------------------------------------------


def test_query_strips_prefix_collapses_whitespace_and_drops_quotes() -> None:
    assert normalize_query("NASA-UAP-D024, “Apollo 16   Scientific\tDebriefing”") == (
        "Apollo 16 Scientific Debriefing"
    )
    assert normalize_query('NASA-UAP-D003A,  Gemini "7" Audio Excerpt, 1965') == "Gemini 7 Audio Excerpt, 1965"


def _pre2015_nasa(card_id: str, title: str, **over: Any) -> dict[str, Any]:
    return _card(card_id=card_id, title=title, **over)


def test_only_unresolved_nasa_cards_are_selected() -> None:
    manifest = {
        "cards": [
            _pre2015_nasa("n1", "NASA-UAP-D001, Apollo 12 Transcript, 1969"),
            _pre2015_nasa("n2", "NASA-UAP-D030, STS-80 Unidentified Object Image 1, 1996", incident_date="1996"),
            _pre2015_nasa("n3", "NASA-UAP-D090, Modern Thing, 2019", incident_date="2019"),
            _pre2015_nasa("f1", "FBI-UAP-D001, Some File, 1969", agency="FBI"),
        ]
    }
    ids = [c["card_id"] for c in unresolved_nasa_cards(manifest)]
    assert ids == ["n1", "n2"]


# --- matching ----------------------------------------------------------------


def test_threshold_is_a_named_constant() -> None:
    assert MATCH_THRESHOLD == 0.9


def test_the_real_sample_matches_by_title() -> None:
    result_title = _sample()["results"][0]["title"]
    assert title_matches("NASA-UAP-D099, Apollo 12 Medical Debriefing", result_title)


def test_a_keyword_only_overlap_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Mission Report on Medical Supplies")
    assert not title_matches("Apollo 12 Medical Debriefing", "Medical Debriefing Procedures for Shuttle Crews")
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo")


def test_a_different_document_with_the_same_topic_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Technical Crew Debriefing")


# --- dates and claims --------------------------------------------------------


def test_the_real_sample_post_dating_the_release_gives_no_claim() -> None:
    search = evaluate_card(_card(), _sample(), _TODAY)
    assert search.claim is None
    assert search.result == RESULT_POST_DATING
    assert search.copies[0]["established_date"] == "2026-07-21"
    assert search.copies[0]["date_basis"] == "ntrs_distribution_date"
    assert search.copies[0]["record_url"] == "https://ntrs.nasa.gov/citations/20260006073"


def test_a_copy_dated_on_the_release_date_gives_no_claim() -> None:
    data = _variant(distributionDate="2026-05-08T04:00:00.0000000+00:00")
    search = evaluate_card(_card(), data, _TODAY)
    assert search.claim is None
    assert search.result == RESULT_POST_DATING


def test_a_copy_dated_before_the_release_gives_content_previously_published() -> None:
    data = _variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
    search = evaluate_card(_card(), data, _TODAY)
    claim = search.claim
    assert claim is not None
    assert search.result == RESULT_CLAIM
    assert claim.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED
    assert claim.source is ResolutionSource.NTRS_METADATA
    assert claim.card_id == "c-apollo12"
    assert claim.identifier_value == "20260006073"
    assert claim.artifact_url == "https://ntrs.nasa.gov/citations/20260006073"
    assert claim.established_date == date(2026, 4, 1)
    assert claim.date_basis is DateBasis.NTRS_DISTRIBUTION_DATE


def test_created_is_the_fallback_date_with_its_own_basis() -> None:
    data = _variant(distributionDate=None, created="2026-03-02T14:23:08.0729640+00:00")
    claim = evaluate_card(_card(), data, _TODAY).claim
    assert claim is not None
    assert claim.established_date == date(2026, 3, 2)
    assert claim.date_basis is DateBasis.NTRS_CREATED_DATE


def test_publication_date_is_never_the_established_date() -> None:
    # The sample's publicationDate is 1969-12-01: the document's own date, which
    # would pre-date any release. It must not turn a post-dating copy into a claim.
    assert _sample()["results"][0]["publications"][0]["publicationDate"].startswith("1969")
    assert evaluate_card(_card(), _sample(), _TODAY).claim is None
    data = _variant(distributionDate=None, created=None)
    search = evaluate_card(_card(), data, _TODAY)
    assert search.claim is None


def test_the_earliest_prior_matching_copy_is_the_one_cited() -> None:
    data = _variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
    other = copy.deepcopy(data["results"][0])
    other["id"] = 20250000001
    other["distributionDate"] = "2025-01-15T04:00:00.0000000+00:00"
    data["results"].append(other)
    claim = evaluate_card(_card(), data, _TODAY).claim
    assert claim is not None
    assert claim.identifier_value == "20250000001"
    assert claim.established_date == date(2025, 1, 15)


def test_an_unrelated_result_dated_before_the_release_gives_no_claim() -> None:
    data = _variant(title="Apollo 12 Mission Report on Medical Supplies", distributionDate="2020-01-01T00:00:00+00:00")
    search = evaluate_card(_card(), data, _TODAY)
    assert search.claim is None
    assert search.result == RESULT_NO_COPY


# --- no hit ------------------------------------------------------------------


def test_no_result_is_recorded_as_searched_with_the_literal_query() -> None:
    search = evaluate_card(_card(), {"stats": {"total": 0}, "results": []}, _TODAY)
    assert search.claim is None
    assert search.result == RESULT_NO_COPY
    row = search.to_dict()
    assert row["query"] == "Apollo 12 Medical Debriefing"
    assert row["searched_date"] == "2026-11-25"
    assert row["card_id"] == "c-apollo12"


def test_nothing_written_claims_novelty() -> None:
    manifest = {"cards": [_card()]}
    for payload in ({"results": []}, _sample(), _variant(distributionDate="2026-04-01T00:00:00+00:00")):
        net = _Net(_Resp(200, payload))
        searches = run_searches(manifest, net.fetcher(), _TODAY)
        text = json.dumps(build_output(manifest, searches, net.fetcher().fetch_counts())).lower()
        assert "not previously released" not in text
        assert "novel" not in text


# --- run and output ----------------------------------------------------------


def test_run_searches_queries_each_unresolved_nasa_card_once() -> None:
    manifest = {
        "cards": [
            _card(card_id="a"),
            _card(card_id="b", title="NASA-UAP-D098, Gemini 7 Transcript, 1965"),
            _card(card_id="f", agency="FBI"),
        ]
    }
    net = _Net()
    searches = run_searches(manifest, net.fetcher(), _TODAY)
    assert [s.card_id for s in searches] == ["a", "b"]
    assert len(net.urls) == 2
    assert "q=Gemini+7+Transcript%2C+1965" in net.urls[1]


def test_output_has_schema_card_count_fetch_counts_and_claims() -> None:
    manifest = {"cards": [_card(), _card(card_id="f", agency="FBI")]}
    net = _Net(_Resp(200, _variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    fetcher = net.fetcher()
    searches = run_searches(manifest, fetcher, _TODAY)
    out = build_output(manifest, searches, fetcher.fetch_counts())
    assert out["schema"] == ntrs_source.SCHEMA
    assert out["card_count"] == 2
    assert out["fetch"] == {"requests": 1, "status_counts": {"200": 1}}
    assert out["claim_count"] == 1
    assert out["claims"][0]["tier"] == "content_previously_published"
    assert out["claims"][0]["date_basis"] == "ntrs_distribution_date"
    assert out["searches"][0]["result"] == RESULT_CLAIM


def test_claims_in_the_output_round_trip_into_the_report_loader() -> None:
    from pursue_index.ntrs_claims_load import load_ntrs_claims

    manifest = {"cards": [_card()]}
    net = _Net(_Resp(200, _variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    searches = run_searches(manifest, net.fetcher(), _TODAY)
    out = build_output(manifest, searches, {})
    loaded = load_ntrs_claims(out)
    assert [c.card_id for c in loaded] == ["c-apollo12"]
    assert load_ntrs_claims({"claims": []}) == []


# --- report wiring -----------------------------------------------------------


def test_a_positive_ntrs_claim_moves_a_card_from_unresolved_to_claim() -> None:
    manifest = {"cards": [_card()]}
    before = build_report(manifest)
    assert before.unresolved == 1
    assert before.outcomes[0].resolved_by == UNRESOLVED

    claim = evaluate_card(_card(), _variant(distributionDate="2026-04-01T00:00:00+00:00"), _TODAY).claim
    assert claim is not None
    after = build_report(manifest, ntrs_claims=[claim])
    assert after.outcomes[0].resolved_by == RESOLVED_BY_CLAIM
    assert after.outcomes[0].primary_tier == "content_previously_published"
    assert after.resolved_by_claim == 1
    assert after.unresolved == 0
    assert after.tier_counts == {"content_previously_published": 1}


def test_an_ntrs_claim_for_another_card_does_not_resolve_this_one() -> None:
    claim = evaluate_card(
        _card(card_id="someone-else"), _variant(distributionDate="2026-04-01T00:00:00+00:00"), _TODAY
    ).claim
    assert claim is not None
    report = build_report({"cards": [_card()]}, ntrs_claims=[claim])
    assert report.unresolved == 1


def test_the_precedence_helper_sees_ntrs_claims() -> None:
    from pursue_index.claim_precedence import positive_claims

    claim = evaluate_card(_card(), _variant(distributionDate="2026-04-01T00:00:00+00:00"), _TODAY).claim
    assert claim is not None
    found = positive_claims(_card(), (), [claim])
    assert [(c.tier, c.source, c.evidence) for c in found] == [
        (
            ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
            "ntrs_metadata",
            "https://ntrs.nasa.gov/citations/20260006073",
        )
    ]
