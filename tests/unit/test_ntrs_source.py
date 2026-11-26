"""NASA NTRS metadata source: title matching, dated claims, report wiring.

Fixture-driven: no socket, no real waiting. The one real response is
``tests/fixtures/ntrs-search-apollo12-debrief.json``.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Any

from pursue_index import ntrs_match, ntrs_source
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
)
from pursue_index.provenance import DateBasis, ProvenanceTier
from pursue_index.provenance_report import RESOLVED_BY_CLAIM, UNRESOLVED, build_report
from pursue_index.resolved_claim import ResolutionSource
from tests.support.ntrs_fakes import TODAY, Net, Resp, card, sample, variant

# --- selection and query -----------------------------------------------------


def test_query_strips_prefix_collapses_whitespace_and_drops_quotes() -> None:
    assert normalize_query("NASA-UAP-D024, “Apollo 16   Scientific\tDebriefing”") == (
        "Apollo 16 Scientific Debriefing"
    )
    assert normalize_query('NASA-UAP-D003A,  Gemini "7" Audio Excerpt, 1965') == "Gemini 7 Audio Excerpt"


def _pre2015_nasa(card_id: str, title: str, **over: Any) -> dict[str, Any]:
    return card(card_id=card_id, title=title, **over)


# --- matching ----------------------------------------------------------------


def test_threshold_is_a_named_constant() -> None:
    assert MATCH_THRESHOLD == 0.9


def test_the_real_sample_matches_by_title() -> None:
    result_title = sample()["results"][0]["title"]
    assert title_matches("NASA-UAP-D099, Apollo 12 Medical Debriefing", result_title)


def test_a_keyword_only_overlap_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Mission Report on Medical Supplies")
    assert not title_matches("Apollo 12 Medical Debriefing", "Medical Debriefing Procedures for Shuttle Crews")
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo")


def test_a_different_document_with_the_same_topic_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Technical Crew Debriefing")


def test_the_title_match_limits_are_named_constants() -> None:
    assert ntrs_match.MAX_EXTRA_RESULT_TOKENS == 2
    assert ntrs_match.MAX_EXTRA_CARD_TOKENS == 1
    assert ntrs_match.MIN_SHARED_TOKENS == 3


def test_an_exact_title_matches() -> None:
    assert title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Medical Debriefing")


def test_a_short_card_title_does_not_match_a_longer_document() -> None:
    assert not title_matches("Apollo 12", "Apollo 12 Lunar Surface Journal Index")


def test_a_result_with_three_extra_tokens_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Medical Debriefing Transcription Of Crew")


def test_a_card_with_two_tokens_missing_from_the_result_does_not_match() -> None:
    assert not title_matches("Apollo 12 Medical Debriefing Report Summary", "Apollo 12 Medical Debriefing")


def test_the_real_sample_with_one_extra_result_token_matches() -> None:
    assert title_matches("Apollo 12 Medical Debriefing", "Apollo 12 Medical Debriefing Transcription")


# --- dates and claims --------------------------------------------------------


def test_the_real_sample_post_dating_the_release_gives_no_claim() -> None:
    search = evaluate_card(card(), sample(), TODAY)
    assert search.claim is None
    assert search.result == RESULT_POST_DATING
    assert search.copies[0]["established_date"] == "2026-07-21"
    assert search.copies[0]["date_basis"] == "ntrs_distribution_date"
    assert search.copies[0]["record_url"] == "https://ntrs.nasa.gov/citations/20260006073"


def test_a_copy_dated_on_the_release_date_gives_no_claim() -> None:
    data = variant(distributionDate="2026-05-08T04:00:00.0000000+00:00")
    search = evaluate_card(card(), data, TODAY)
    assert search.claim is None
    assert search.result == RESULT_POST_DATING


def test_a_copy_dated_before_the_release_gives_content_previously_published() -> None:
    data = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
    search = evaluate_card(card(), data, TODAY)
    claim = search.claim
    assert claim is not None
    assert search.result == RESULT_CLAIM
    assert claim.tier is ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED
    assert claim.source is ResolutionSource.NTRS_METADATA
    assert claim.card_id == "a0a0a0a0a0a0a012"
    assert claim.identifier_value == "20260006073"
    assert claim.artifact_url == "https://ntrs.nasa.gov/citations/20260006073"
    assert claim.established_date == date(2026, 4, 1)
    assert claim.date_basis is DateBasis.NTRS_DISTRIBUTION_DATE


def test_created_is_the_fallback_date_with_its_own_basis() -> None:
    data = variant(distributionDate=None, created="2026-03-02T14:23:08.0729640+00:00")
    claim = evaluate_card(card(), data, TODAY).claim
    assert claim is not None
    assert claim.established_date == date(2026, 3, 2)
    assert claim.date_basis is DateBasis.NTRS_CREATED_DATE


def test_publication_date_is_never_the_established_date() -> None:
    # The sample's publicationDate is 1969-12-01: the document's own date, which
    # would pre-date any release. It must not turn a post-dating copy into a claim.
    assert sample()["results"][0]["publications"][0]["publicationDate"].startswith("1969")
    assert evaluate_card(card(), sample(), TODAY).claim is None
    data = variant(distributionDate=None, created=None)
    search = evaluate_card(card(), data, TODAY)
    assert search.claim is None


def test_the_earliest_prior_matching_copy_is_the_one_cited() -> None:
    data = variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")
    other = copy.deepcopy(data["results"][0])
    other["id"] = 20250000001
    other["distributionDate"] = "2025-01-15T04:00:00.0000000+00:00"
    data["results"].append(other)
    claim = evaluate_card(card(), data, TODAY).claim
    assert claim is not None
    assert claim.identifier_value == "20250000001"
    assert claim.established_date == date(2025, 1, 15)


def test_an_unrelated_result_dated_before_the_release_gives_no_claim() -> None:
    data = variant(title="Apollo 12 Mission Report on Medical Supplies", distributionDate="2020-01-01T00:00:00+00:00")
    search = evaluate_card(card(), data, TODAY)
    assert search.claim is None
    assert search.result == RESULT_NO_COPY


# --- no hit ------------------------------------------------------------------


def test_no_result_is_recorded_as_searched_with_the_literal_query() -> None:
    search = evaluate_card(card(), {"stats": {"total": 0}, "results": []}, TODAY)
    assert search.claim is None
    assert search.result == RESULT_NO_COPY
    row = search.to_dict()
    assert row["query"] == "Apollo 12 Medical Debriefing"
    assert row["searched_date"] == "2026-11-25"
    assert row["card_id"] == "a0a0a0a0a0a0a012"


def test_nothing_written_claims_novelty() -> None:
    manifest = {"cards": [card()]}
    for payload in ({"results": []}, sample(), variant(distributionDate="2026-04-01T00:00:00+00:00")):
        net = Net(Resp(200, payload))
        searches = run_searches(manifest, net.fetcher(), TODAY)
        text = json.dumps(build_output(manifest, searches, net.fetcher().fetch_counts())).lower()
        assert "not previously released" not in text
        assert "novel" not in text


# --- run and output ----------------------------------------------------------


def test_run_searches_queries_each_unresolved_nasa_card_once() -> None:
    manifest = {
        "cards": [
            card(card_id="a"),
            card(card_id="b", title="NASA-UAP-D098, Gemini 7 Transcript, 1965"),
            card(card_id="f", agency="FBI"),
        ]
    }
    net = Net()
    searches = run_searches(manifest, net.fetcher(), TODAY)
    assert [s.card_id for s in searches] == ["a", "b"]
    assert len(net.urls) == 2
    assert "q=Gemini+7+Transcript&" in net.urls[1]


def test_output_has_schema_card_count_fetch_counts_and_claims() -> None:
    manifest = {"cards": [card(), card(card_id="f", agency="FBI")]}
    net = Net(Resp(200, variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    fetcher = net.fetcher()
    searches = run_searches(manifest, fetcher, TODAY)
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

    manifest = {"cards": [card()]}
    net = Net(Resp(200, variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    searches = run_searches(manifest, net.fetcher(), TODAY)
    out = build_output(manifest, searches, {})
    loaded = load_ntrs_claims(out)
    assert [c.card_id for c in loaded.claims] == ["a0a0a0a0a0a0a012"]
    assert load_ntrs_claims({"claims": []}).claims == []


# --- report wiring -----------------------------------------------------------


def test_a_positive_ntrs_claim_moves_a_card_from_unresolved_to_claim() -> None:
    manifest = {"cards": [card()]}
    before = build_report(manifest)
    assert before.unresolved == 1
    assert before.outcomes[0].resolved_by == UNRESOLVED

    claim = evaluate_card(card(), variant(distributionDate="2026-04-01T00:00:00+00:00"), TODAY).claim
    assert claim is not None
    after = build_report(manifest, extra_claims=[claim])
    assert after.outcomes[0].resolved_by == RESOLVED_BY_CLAIM
    assert after.outcomes[0].primary_tier == "content_previously_published"
    assert after.resolved_by_claim == 1
    assert after.unresolved == 0
    assert after.tier_counts == {"content_previously_published": 1}


def test_an_ntrs_claim_for_another_card_does_not_resolve_this_one() -> None:
    claim = evaluate_card(
        card(card_id="someone-else"), variant(distributionDate="2026-04-01T00:00:00+00:00"), TODAY
    ).claim
    assert claim is not None
    report = build_report({"cards": [card()]}, extra_claims=[claim])
    assert report.unresolved == 1


def test_the_precedence_helper_sees_ntrs_claims() -> None:
    from pursue_index.claim_precedence import positive_claims

    claim = evaluate_card(card(), variant(distributionDate="2026-04-01T00:00:00+00:00"), TODAY).claim
    assert claim is not None
    found = positive_claims(card(), (), [claim])
    assert [(c.tier, c.source, c.evidence) for c in found] == [
        (
            ProvenanceTier.CONTENT_PREVIOUSLY_PUBLISHED,
            "ntrs_metadata",
            "https://ntrs.nasa.gov/citations/20260006073",
        )
    ]


# --- the CLI run -------------------------------------------------------------


def _repo_with_manifest(root: Path, cards: list[dict[str, Any]]) -> None:
    (root / "data" / "manifests").mkdir(parents=True)
    (root / "data" / "manifests" / "latest.json").write_text(json.dumps({"cards": cards}))


def test_run_writes_the_artifact(tmp_path: Path) -> None:
    _repo_with_manifest(tmp_path, [card()])
    net = Net(Resp(200, variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    assert ntrs_source.run(tmp_path, net.fetcher(), TODAY) == 0
    written = json.loads((tmp_path / ntrs_source.OUTPUT_PATH).read_text())
    assert written["claim_count"] == 1
    assert written["fetch"]["requests"] == 1


def test_run_aborts_on_429_and_writes_nothing(tmp_path: Path) -> None:
    _repo_with_manifest(tmp_path, [card(card_id="a"), card(card_id="b")])
    net = Net(Resp(429))
    assert ntrs_source.run(tmp_path, net.fetcher(), TODAY) == 1
    assert not (tmp_path / ntrs_source.OUTPUT_PATH).exists()
    assert net.events.count("get") == 1


def test_the_report_cli_reads_the_stored_claims(tmp_path: Path) -> None:
    from pursue_index.ntrs_claims_load import read_ntrs_claims

    assert read_ntrs_claims(tmp_path) is None
    _repo_with_manifest(tmp_path, [card()])
    net = Net(Resp(200, variant(distributionDate="2026-04-01T04:00:00.0000000+00:00")))
    ntrs_source.run(tmp_path, net.fetcher(), TODAY)
    stored = read_ntrs_claims(tmp_path)
    assert stored is not None
    assert [c.card_id for c in stored.claims] == ["a0a0a0a0a0a0a012"]
