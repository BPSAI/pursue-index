"""One source file has one era: the dated row's era wins for every row of it.

Rows sharing a ``card_id`` name one file. An undated row of a file with exactly
one resolved era takes that era from the dated row and is labelled with that
row's key. Upstream fields are mirrored unchanged.
"""

from __future__ import annotations

from typing import Any

from pursue_index.era_bucketing import bucket, build_output
from pursue_index.era_models import Era


def _row(card_id: str, title: str, **dates: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "agency": "DOW", "release_date": "5/8/2026", **dates}


def _dated(card_id: str = "aaaa", title: str = "D1", date: str = "2022-05-06") -> dict[str, Any]:
    return _row(card_id, title, incident_date=date)


def test_a_dated_row_and_an_undated_row_of_one_file_end_with_one_era() -> None:
    result = bucket({"cards": [_dated(), _row("aaaa", "PR1")]})
    dated, undated = result.cards
    assert dated.era is undated.era is Era.MODERN_OPERATIONAL
    assert undated.era_reconciled_from == "aaaa#0"
    assert dated.era_reconciled_from is None
    assert undated.year == dated.year
    assert undated.date_source == "reconciled_from_sibling"
    assert result.triage == []
    assert result.era_counts["undated"] == 0


def test_the_dated_row_may_come_after_the_undated_row() -> None:
    result = bucket({"cards": [_row("aaaa", "PR1"), _dated()]})
    assert result.cards[0].era_reconciled_from == "aaaa#1"
    assert result.cards[0].era is Era.MODERN_OPERATIONAL


def test_three_rows_one_dated_two_undated_reconcile_both() -> None:
    result = bucket({"cards": [_dated(), _row("aaaa", "PR1"), _row("aaaa", "PR2")]})
    assert [c.era_reconciled_from for c in result.cards] == [None, "aaaa#0", "aaaa#0"]
    assert {c.era for c in result.cards} == {Era.MODERN_OPERATIONAL}
    assert result.triage == []


def test_a_single_row_undated_file_is_unchanged() -> None:
    result = bucket({"cards": [_row("aaaa", "PR1")]})
    (card,) = result.cards
    assert card.era is Era.UNDATED
    assert card.era_reconciled_from is None
    assert [t["row_key"] for t in result.triage] == ["aaaa#0"]


def test_a_file_with_no_dated_row_stays_undated() -> None:
    result = bucket({"cards": [_row("aaaa", "PR1"), _row("aaaa", "PR2")]})
    assert [c.era for c in result.cards] == [Era.UNDATED, Era.UNDATED]
    assert len(result.triage) == 2


def test_conflicting_eras_reconcile_nothing_and_say_why() -> None:
    cards = [_dated(date="2022-05-06"), _dated(title="D2", date="1975"), _row("aaaa", "PR1")]
    result = bucket({"cards": cards})
    assert [c.era for c in result.cards] == [Era.MODERN_OPERATIONAL, Era.ERA_1970_1989, Era.UNDATED]
    assert all(c.era_reconciled_from is None for c in result.cards)
    assert [t["row_key"] for t in result.triage] == ["aaaa#0", "aaaa#1", "aaaa#2"]
    entry = result.triage[2]
    assert entry["reason"] == (
        "conflicting document dates across rows of the same file: "
        "aaaa#0=2015_plus/2022, aaaa#1=1970_1989/1975"
    )


def test_a_row_that_is_already_dated_keeps_its_own_era() -> None:
    result = bucket({"cards": [_dated(), _dated(title="D2", date="1975")]})
    assert [c.era for c in result.cards] == [Era.MODERN_OPERATIONAL, Era.ERA_1970_1989]
    assert all(c.era_reconciled_from is None for c in result.cards)


def test_a_guard_held_card_with_no_dated_sibling_is_still_undated() -> None:
    held = _row("aaaa", "Mission Report", incident_date="6/7/2024")
    result = bucket({"cards": [held]})
    assert result.cards[0].era is Era.UNDATED
    assert "uncorroborated" in result.triage[0]["reason"]


def test_a_guard_held_sibling_does_not_count_as_a_dated_row() -> None:
    held = _row("aaaa", "Mission Report", incident_date="6/7/2024")
    result = bucket({"cards": [held, _row("aaaa", "PR1")]})
    assert [c.era for c in result.cards] == [Era.UNDATED, Era.UNDATED]
    assert all(c.era_reconciled_from is None for c in result.cards)


def test_a_reconciled_row_takes_the_modern_record_and_names_its_source() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1")]}
    out = build_output(manifest, bucket(manifest))
    by_key = {r["row_key"]: r for r in out["no_prior_release"]}
    assert set(by_key) == {"aaaa#0", "aaaa#1"}
    assert by_key["aaaa#1"]["era_reconciled_from"] == "aaaa#0"
    assert by_key["aaaa#1"]["established_year"] == by_key["aaaa#0"]["established_year"] == 2022
    assert "era_reconciled_from" not in by_key["aaaa#0"]
    assert out["era_counts"]["2015_plus"] == 1
    assert out["undated_triage_row_count"] == 0
    cards = {c["row_key"]: c for c in out["cards"]}
    assert cards["aaaa#1"]["era_reconciled_from"] == "aaaa#0"
    assert cards["aaaa#0"]["era_reconciled_from"] is None


def _fixture_manifest() -> dict[str, Any]:
    """A small manifest: reconciled, undated, conflicting and lone-undated files."""
    return {
        "cards": [
            _dated("aaaa", "D1") | {"asset_filename": "d1.pdf"},
            _row("aaaa", "PR1"),
            _row("bbbb", "Lone", incident_date="n.d."),
            _dated("cccc", "C1", "2022-05-06"),
            _dated("cccc", "C2", "2019-03-04"),
            _row("cccc", "C3", display_date="undated"),
            {"card_id": "dddd", "agency": "DOW"},
        ]
    }


def test_no_upstream_field_changes_over_a_fixture_manifest() -> None:
    manifest = _fixture_manifest()
    out = build_output(manifest, bucket(manifest))
    assert len(out["cards"]) == len(manifest["cards"])
    for card, entry in zip(manifest["cards"], out["cards"], strict=True):
        assert entry["card_id"] == card["card_id"]
        assert entry["title"] == str(card.get("title") or "")
        assert entry["identifier"] == str(
            card.get("asset_filename") or card.get("title") or card.get("card_id") or ""
        )


def test_triage_rows_mirror_the_manifest_dates_over_a_fixture_manifest() -> None:
    manifest = _fixture_manifest()
    out = build_output(manifest, bucket(manifest))
    by_key = {f"{c['card_id']}#{i}": c for c in manifest["cards"] for i in [_index(manifest, c)]}
    assert {r["row_key"] for r in out["undated_triage"]} >= {"bbbb#0", "cccc#2", "dddd#0"}
    for row in out["undated_triage"]:
        card = by_key[row["row_key"]]
        assert row["title"] == str(card.get("title") or "")
        assert row["available_dates"] == {
            "display_date": card.get("display_date"),
            "incident_date": card.get("incident_date"),
            "release_date": card.get("release_date"),
        }


def _index(manifest: dict[str, Any], card: dict[str, Any]) -> int:
    """The row's position among the rows sharing its card_id."""
    same = [c for c in manifest["cards"] if c["card_id"] == card["card_id"]]
    return next(i for i, c in enumerate(same) if c is card)


def test_a_fixture_manifest_without_conflicts_has_one_era_per_file() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1"), _row("aaaa", "PR2"), _dated("bbbb", "B", "1975")]}
    eras: dict[str, set[str]] = {}
    for entry in build_output(manifest, bucket(manifest))["cards"]:
        eras.setdefault(entry["card_id"], set()).add(entry["era"])
    assert eras == {"aaaa": {"2015_plus"}, "bbbb": {"1970_1989"}}


def test_same_era_with_different_years_is_a_conflict_and_reconciles_nothing() -> None:
    cards = [_dated(date="2022-05-06"), _dated(title="D2", date="2019-03-04"), _row("aaaa", "PR1")]
    result = bucket({"cards": cards})
    assert [c.era for c in result.cards][:2] == [Era.MODERN_OPERATIONAL, Era.MODERN_OPERATIONAL]
    assert result.cards[2].era is Era.UNDATED
    assert all(c.era_reconciled_from is None for c in result.cards)
    assert [t["row_key"] for t in result.triage] == ["aaaa#0", "aaaa#1", "aaaa#2"]
    entry = result.triage[2]
    assert entry["reason"] == (
        "conflicting document dates across rows of the same file: "
        "aaaa#0=2015_plus/2022, aaaa#1=2015_plus/2019"
    )


def test_same_era_with_the_same_year_is_reconciled() -> None:
    cards = [_dated(date="2022-05-06"), _dated(title="D2", date="2022-11-30"), _row("aaaa", "PR1")]
    result = bucket({"cards": cards})
    assert result.cards[2].era is Era.MODERN_OPERATIONAL
    assert result.cards[2].year == 2022
    assert result.cards[2].era_reconciled_from == "aaaa#0"
    assert result.triage == []


def test_a_reconciled_row_names_the_inference_as_its_date_source() -> None:
    manifest = {"cards": [_dated(), _row("aaaa", "PR1")]}
    result = bucket(manifest)
    dated, undated = result.cards
    assert dated.date_source == "incident_date"
    assert undated.date_source == "reconciled_from_sibling"
    assert undated.era_reconciled_from == "aaaa#0"
    assert undated.year == dated.year
    out = build_output(manifest, result)
    cards = {c["row_key"]: c for c in out["cards"]}
    assert cards["aaaa#0"]["date_source"] == "incident_date"
    assert cards["aaaa#1"]["date_source"] == "reconciled_from_sibling"
    record = {r["row_key"]: r for r in out["no_prior_release"]}["aaaa#1"]
    assert record["date_source"] == "reconciled_from_sibling"
    assert record["era_reconciled_from"] == "aaaa#0"
    assert "incident_date" not in record["rationale"]
