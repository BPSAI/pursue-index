"""The judge's per-page rate comes from metered spend, or says it doesn't (R7C.5).

``read_judge_rate`` reads the committed ``clean-qc-bundle.json``: when the
judge's spend ledger has been folded in (``metered_judge_spend_usd`` and
``metered_judge_calls``) the rate is their quotient, labeled ``metered``;
otherwise the table's judge figure, labeled ``table estimate``. The bundle's
``est_total_cost_usd`` is a pre-run projection, not spend, and is never read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pursue_index.release import rates
from pursue_index.release.rates import (
    JUDGE_METERED,
    JUDGE_TABLE_ESTIMATE,
    RATES_TABLE,
    cost_band,
    read_judge_rate,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMITTED_BUNDLE = _REPO_ROOT / "web" / "public" / "data" / "clean-qc-bundle.json"


def _bundle(tmp_path: Path, stats: dict) -> Path:
    path = tmp_path / "clean-qc-bundle.json"
    path.write_text(json.dumps({"bundle_schema_version": 1, "cards": [], "stats": stats}))
    return path


def test_current_bundle_yields_the_metered_rate(tmp_path: Path) -> None:
    path = _bundle(tmp_path, {
        "metered_judge_spend_usd": 20.0, "metered_judge_calls": 1_000,
        "est_total_cost_usd": 999.0, "judge_calls": 1_000,
    })
    judge = read_judge_rate(path)
    assert judge.usd_per_page == pytest.approx(0.02)
    assert judge.label == JUDGE_METERED


def test_old_schema_bundle_falls_back_to_the_table_never_the_projection(tmp_path: Path) -> None:
    path = _bundle(tmp_path, {"est_total_cost_usd": 216.6, "judge_calls": 12_407})
    judge = read_judge_rate(path)
    assert judge.usd_per_page == RATES_TABLE["judge"].low
    assert judge.label == JUDGE_TABLE_ESTIMATE


@pytest.mark.parametrize("content", [None, "", "{}", "not json", "[]"])
def test_empty_or_missing_bundle_falls_back_to_the_table(tmp_path: Path, content) -> None:
    path = tmp_path / "clean-qc-bundle.json"
    if content is not None:
        path.write_text(content)
    judge = read_judge_rate(path)
    assert (judge.usd_per_page, judge.label) == (RATES_TABLE["judge"].low, JUDGE_TABLE_ESTIMATE)


@pytest.mark.parametrize("stats", [
    {"metered_judge_spend_usd": 20.0, "metered_judge_calls": 0},
    {"metered_judge_spend_usd": 20.0},
    {"metered_judge_calls": 1_000},
    {"metered_judge_spend_usd": "20", "metered_judge_calls": 1_000},
])
def test_either_field_missing_or_zero_calls_falls_back(tmp_path: Path, stats: dict) -> None:
    assert read_judge_rate(_bundle(tmp_path, stats)).label == JUDGE_TABLE_ESTIMATE


def _assert_labeled_truthfully(path: Path) -> None:
    """A ``metered`` rate is the bundle's own spend / calls; a ``table
    estimate`` is the table's figure. Neither label ever carries the other's
    number, whichever the bundle happens to contain."""
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    judge = read_judge_rate(path)
    assert judge.label in (JUDGE_METERED, JUDGE_TABLE_ESTIMATE)
    if judge.label == JUDGE_METERED:
        block = stats if "metered_judge_calls" in stats else data
        assert judge.usd_per_page == pytest.approx(
            block["metered_judge_spend_usd"] / block["metered_judge_calls"])
    else:
        assert judge.usd_per_page == RATES_TABLE["judge"].low


def test_the_committed_bundle_is_labeled_truthfully() -> None:
    """The committed bundle may predate the judge's spend ledger (R7C.6) or
    carry it, as clean-qc bundles from the metered judge do."""
    _assert_labeled_truthfully(_COMMITTED_BUNDLE)


def test_the_committed_bundle_with_metered_fields_folded_in_reads_metered(
    tmp_path: Path,
) -> None:
    """The same bundle once the metered judge has written its spend."""
    data = json.loads(_COMMITTED_BUNDLE.read_text(encoding="utf-8"))
    data.setdefault("stats", {}).update(
        {"metered_judge_spend_usd": 10.11, "metered_judge_calls": 574})
    path = tmp_path / "clean-qc-bundle.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_judge_rate(path).label == JUDGE_METERED
    _assert_labeled_truthfully(path)


def test_the_committed_bundle_without_metered_fields_reads_table_estimate(
    tmp_path: Path,
) -> None:
    data = json.loads(_COMMITTED_BUNDLE.read_text(encoding="utf-8"))
    for block in (data, data.get("stats") or {}):
        block.pop("metered_judge_spend_usd", None)
        block.pop("metered_judge_calls", None)
    path = tmp_path / "clean-qc-bundle.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_judge_rate(path).label == JUDGE_TABLE_ESTIMATE
    _assert_labeled_truthfully(path)


def test_rates_module_never_names_the_projection_field() -> None:
    assert "est_total_cost_usd" not in Path(rates.__file__).read_text(encoding="utf-8")


def test_band_carries_the_judge_rate_and_its_label(tmp_path: Path) -> None:
    metered = read_judge_rate(_bundle(tmp_path, {
        "metered_judge_spend_usd": 30.0, "metered_judge_calls": 1_000,
    }))
    band = cost_band(100, judge=metered)
    assert band.stages["judge"].low == pytest.approx(100 * 0.03)
    assert band.judge_label == JUDGE_METERED
    assert cost_band(100).judge_label == JUDGE_TABLE_ESTIMATE


@pytest.mark.parametrize("spend,calls", [(5_000.0, 10), (-1.0, 10)])
def test_an_out_of_range_metered_rate_falls_back_without_collapsing_the_band(
    tmp_path: Path, spend: float, calls: int
) -> None:
    path = _bundle(tmp_path, {"metered_judge_spend_usd": spend, "metered_judge_calls": calls})
    judge = read_judge_rate(path)
    assert (judge.usd_per_page, judge.label) == (RATES_TABLE["judge"].low, JUDGE_TABLE_ESTIMATE)
    assert cost_band(10, judge=judge).high > 0
