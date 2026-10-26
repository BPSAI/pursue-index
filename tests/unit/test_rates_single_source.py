"""``release/rates.py`` is the only place a per-page cost is defined (R7C.5).

Swapping the rates table must move every figure the poll summary and
``pursue ingest run`` print; and no other module may define a per-page USD
constant of its own (``ship.py`` used to carry ``_OCR_USD_PER_PAGE`` and
``_EMBED_USD_PER_PAGE``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app
from pursue_index.release import rates, ship
from pursue_index.release.rates import StageRate
from pursue_index.scrape.classify_tranche import render_verdict_summary
from pursue_index.scrape.poll_snapshot import SnapshotDiffResult
from pursue_index.scrape.types import CardMetadata

_REPO = Path(__file__).resolve().parents[2]
_SHA = "feedface1234" + "0" * 52
# $1/page low, $10/page worst case: a figure no real table would produce.
_SENTINEL_TABLE = {"ocr": StageRate(low=1.0, high=10.0)}


@pytest.fixture
def sentinel_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rates, "RATES_TABLE", _SENTINEL_TABLE)


def test_poll_summary_prices_from_the_rates_table(sentinel_rates) -> None:
    card = CardMetadata(card_id="aaaa000000000001", title="t", asset_type="PDF",
                        agency="FBI", asset_url="https://www.war.gov/a.pdf")
    diff = SnapshotDiffResult(added=[card], removed=[], field_changes=[], new_columns=[])
    text = render_verdict_summary(diff, tranche=_SHA, page_counts={card.card_id: 3})
    assert "$3.00 low to $30.00 worst case over 3 pages" in text


def test_ingest_run_prices_from_the_rates_table(
    sentinel_rates, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(ingest_cli, "gate_resolve_and_promote", lambda *a, **k: None)
    diff_dir = tmp_path / "tranche-diffs"
    diff_dir.mkdir()
    row = {"new_card_id": "aaaa000000000001", "asset_type": "PDF",
           "asset_url": "https://www.war.gov/a.pdf", "page_count": 3}
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps({"new_content": [row]}))
    result = CliRunner().invoke(app, ["ingest", "run", "--tranche", _SHA, "--diff-dir", str(diff_dir)])
    assert result.exit_code == 0, result.output
    assert "$3.00 low to $30.00 worst case over 3 pages" in result.output


def test_ship_cost_estimate_prices_from_the_rates_table(sentinel_rates) -> None:
    assert ship.estimate_cost_usd(pages=3) == 3.0
    assert ship.estimate_cost_usd(cards=1) == float(rates.AVG_PAGES_PER_CARD)


_PER_PAGE_CONSTANT = re.compile(r"^\s*_?[A-Z0-9_]*USD_PER_PAGE[A-Z0-9_]*\s*[:=]", re.MULTILINE)


def test_no_module_but_rates_defines_a_per_page_cost() -> None:
    sources = [*(_REPO / "src" / "pursue_index").rglob("*.py"),
               _REPO / "scripts" / "poll_snapshot.py"]
    offenders = [
        str(p.relative_to(_REPO)) for p in sources
        if p.name != "rates.py" and _PER_PAGE_CONSTANT.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
