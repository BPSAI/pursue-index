"""Provenance coverage report over the full resolution chain.

The report runs the Tier-0 sweep, era bucketing, and the
identifier resolver together and answers one question: how much of the
corpus did Phase A resolve, and how? It draws a line the `/methodology` exit
condition depends on — **cards resolved by a prior-release claim are never
conflated with cards resolved by era alone**:

* A card carrying a positive prior-release claim (Tier-0 or identifier
  resolver) is ``resolved_by == "claim"``, even when it is also a 2015+ card.
* A 2015+ card with *no* positive claim is ``resolved_by == "era"`` — the
  era-based no-prior-release conclusion, counted on its own.
* Everything else (pre-2015 with no claim, or undated) is ``unresolved``.

The report is read-only: it computes and prints, and the CLI refuses to write
anywhere under ``web/``.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.provenance_report import (
    RESOLVED_BY_CLAIM,
    RESOLVED_BY_ERA,
    UNRESOLVED,
    CardOutcome,
    build_report,
    classify,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"

runner = CliRunner()


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


# --------------------------------------------------------------------------- #
# Coverage over the whole corpus partitions every card exactly once           #
# --------------------------------------------------------------------------- #


def test_every_card_is_resolved_by_exactly_one_route() -> None:
    report = build_report(_manifest())
    assert report.card_count == len(_manifest()["cards"])
    assert (
        report.resolved_by_claim + report.resolved_by_era + report.unresolved
        == report.card_count
    )
    assert len(report.outcomes) == report.card_count


def test_real_manifest_coverage_matches_the_chain() -> None:
    """The committed manifest resolves to a stable, known coverage split.

    These figures are pinned against the currently promoted manifest and are
    updated as part of a release promote when the corpus grows.
    """
    report = build_report(_manifest())
    assert report.resolved_by_claim == 23
    # Cards carrying a two-digit incident date that no four-digit year on the
    # card corroborates are undated rather than modern, so they sit in
    # unresolved (triage) instead of taking an era-based negative.
    assert report.resolved_by_era == 195
    assert report.unresolved == 157
    assert report.page_image_flagged == 19
    assert report.tier_counts == {
        "previously_released": 3,
        "previously_released_in_part": 19,
        "content_previously_published": 1,
    }


def test_tier_counts_sum_to_the_claim_total() -> None:
    report = build_report(_manifest())
    assert sum(report.tier_counts.values()) == report.resolved_by_claim


def test_unresolved_by_era_sums_to_unresolved_and_excludes_2015_plus() -> None:
    report = build_report(_manifest())
    assert sum(report.unresolved_by_era.values()) == report.unresolved
    # A 2015+ card is never "unresolved" — it is at least era-resolved.
    assert "2015_plus" not in report.unresolved_by_era


# --------------------------------------------------------------------------- #
# A positive claim is never swallowed by the era conclusion                    #
# --------------------------------------------------------------------------- #


def test_claim_beats_era_so_the_two_are_never_conflated() -> None:
    """A 2015+ card that also carries a claim is counted as claim, not era."""
    card = {
        "card_id": "modern-with-claim",
        "title": "Range debrief",
        "agency": "USAF",
        "display_date": "2018-05-01",
        "description": "These pages were previously released to the public.",
    }
    outcome = classify(card, ())
    assert outcome.era == "2015_plus"
    assert outcome.resolved_by == RESOLVED_BY_CLAIM
    assert outcome.primary_tier == "previously_released"


def test_2015_plus_card_without_a_claim_is_resolved_by_era_alone() -> None:
    card = {
        "card_id": "modern-no-claim",
        "title": "Mission report",
        "agency": "USAF",
        "display_date": "2020-01-01",
        "description": "Routine operational summary.",
    }
    outcome = classify(card, ())
    assert outcome.resolved_by == RESOLVED_BY_ERA
    assert outcome.primary_tier is None
    assert outcome.needs_page_image_comparison is False


def test_old_card_without_a_claim_is_unresolved() -> None:
    card = {
        "card_id": "old-no-claim",
        "title": "1952 sighting",
        "agency": "USAF",
        "display_date": "1952-07-01",
        "description": "Contemporary field report.",
    }
    outcome = classify(card, ())
    assert outcome.resolved_by == UNRESOLVED
    assert outcome.era == "pre_1970"


# --------------------------------------------------------------------------- #
# The page-image flag belongs only to the partial tier                        #
# --------------------------------------------------------------------------- #


def test_page_image_flag_only_on_previously_released_in_part() -> None:
    partial = {
        "card_id": "fbi-vault",
        "title": "62-HQ-83894 section 3",
        "agency": "FBI",
        "description": "This file was partially posted on the FBI vault; some pages missing.",
    }
    outcome = classify(partial, ())
    assert outcome.primary_tier == "previously_released_in_part"
    assert outcome.needs_page_image_comparison is True


def test_report_to_dict_carries_the_headline_numbers_and_unresolved_list() -> None:
    report = build_report(_manifest())
    payload = report.to_dict()
    assert payload["card_count"] == report.card_count
    assert payload["resolved_by_claim"] == report.resolved_by_claim
    assert payload["resolved_by_era"] == report.resolved_by_era
    assert payload["page_image_flagged"] == report.page_image_flagged
    unresolved = payload["unresolved_cards"]
    assert len(unresolved) == report.unresolved
    assert all(row["resolved_by"] == UNRESOLVED for row in unresolved)


def test_card_outcome_round_trips_through_to_dict() -> None:
    outcome = CardOutcome(
        card_id="c1",
        title="t",
        agency="USAF",
        era="pre_1970",
        primary_tier=None,
        resolved_by=UNRESOLVED,
        needs_page_image_comparison=False,
    )
    assert outcome.to_dict()["resolved_by"] == UNRESOLVED
    assert outcome.to_dict()["primary_tier"] is None


# --------------------------------------------------------------------------- #
# The CLI is report-only — it prints the split and never writes under web/     #
# --------------------------------------------------------------------------- #


def test_cli_prints_the_coverage_split() -> None:
    res = runner.invoke(app, ["provenance", "report"])
    assert res.exit_code == 0, res.output
    assert str(len(_manifest()["cards"])) in res.output
    # The two routes appear as separately labelled lines.
    assert "claim" in res.output.lower()
    assert "era" in res.output.lower()
    assert "page-image" in res.output.lower()
    assert "unresolved" in res.output.lower()


def test_cli_refuses_to_write_under_web(tmp_path) -> None:
    web_target = _REPO_ROOT / "web" / "public" / "data" / "should-not-write.json"
    assert not web_target.exists()
    res = runner.invoke(app, ["provenance", "report", "--json-out", str(web_target)])
    assert res.exit_code != 0
    assert not web_target.exists()
    assert "web/" in res.output or "web" in res.output.lower()


def test_cli_optional_json_out_writes_outside_web(tmp_path) -> None:
    out = tmp_path / "coverage.json"
    res = runner.invoke(app, ["provenance", "report", "--json-out", str(out)])
    assert res.exit_code == 0, res.output
    payload = json.loads(out.read_text())
    assert payload["card_count"] == len(_manifest()["cards"])
    assert payload["resolved_by_claim"] + payload["resolved_by_era"] + payload[
        "unresolved"
    ] == payload["card_count"]
