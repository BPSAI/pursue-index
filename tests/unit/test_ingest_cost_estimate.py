"""``pursue ingest run`` and ``ingest approve`` quote the per-page estimate (R7C.5).

Both price the tranche's PDF/IMG work-list from ``release/rates.py``. A
new-content row that carries a ``page_count`` is priced per page; one that
doesn't falls back per card and the figure is marked partial. The approval
prompt and the approval record both carry the judge figure's label --
``metered`` only when the committed clean-qc bundle has the metered fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli import ingest_cli
from pursue_index.cli.commands import app

runner = CliRunner()
_SHA = "c0ffee123456" + "0" * 52
_METERED = {"metered_judge_spend_usd": 20.0, "metered_judge_calls": 1_000}


def _row(card_id: str, page_count: int | None = None) -> dict:
    row = {"new_card_id": card_id, "asset_type": "PDF",
           "asset_url": f"https://www.war.gov/medialink/{card_id}.pdf"}
    if page_count is not None:
        row["page_count"] = page_count
    return row


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PURSUE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(ingest_cli, "enforce_poll_freshness", lambda *a, **k: None)
    monkeypatch.setattr(ingest_cli, "gate_resolve_and_promote", lambda *a, **k: None)
    (tmp_path / "data" / "tranche-diffs").mkdir(parents=True)
    return tmp_path


def _write(repo: Path, rows: list[dict], bundle_stats: dict | None = None) -> None:
    diff = {"tranche_sha256": _SHA, "summary": {"new_content": len(rows)},
            "new_content": rows, "renames_confirmed": [], "quarantined": [],
            "restored_unchanged": [], "restored_modified": [], "field_only_changes": []}
    (repo / "data" / "tranche-diffs" / f"tranche-diff-{_SHA[:12]}.json").write_text(json.dumps(diff))
    bundle = repo / "web" / "public" / "data" / "clean-qc-bundle.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps({"cards": [], "stats": bundle_stats or {}}))


def _invoke(repo: Path, command: str) -> str:
    args = ["ingest", command, "--tranche", _SHA, "--diff-dir", str(repo / "data" / "tranche-diffs"),
            "--log", str(repo / "data" / "tranche-approval-log.jsonl")]
    if command == "approve":
        args += ["--note", "ok", "--skip-audit", "--aliases", str(repo / "data" / "aliases.json")]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


def test_ingest_run_prices_counted_pages(repo: Path) -> None:
    _write(repo, [_row("aaaa000000000001", 40), _row("bbbb000000000002", 71)])
    out = _invoke(repo, "run")
    assert "over 111 pages" in out
    assert "partial" not in out.lower()


def test_ingest_run_without_page_counts_is_partial_and_names_the_cards(repo: Path) -> None:
    _write(repo, [_row("aaaa000000000001", 40), _row("bbbb000000000002")])
    out = _invoke(repo, "run")
    assert "Est. cost (partial)" in out
    assert "`bbbb000000000002`" in out
    assert "`aaaa000000000001`" not in out.split("partial:**", 1)[1]


@pytest.mark.parametrize(("stats", "label", "absent"), [
    ({}, "table estimate", "metered"),
    ({"est_total_cost_usd": 216.6}, "table estimate", "metered"),
    (_METERED, "metered", "table estimate"),
])
def test_approval_prompt_shows_which_judge_label_applies(repo, stats, label, absent) -> None:
    _write(repo, [_row("aaaa000000000001", 10)], stats)
    out = _invoke(repo, "approve")
    assert f"judge rate: {label}" in out
    assert absent not in out


@pytest.mark.parametrize(("stats", "label"), [({}, "table estimate"), (_METERED, "metered")])
def test_approval_record_carries_the_judge_label(repo, stats, label) -> None:
    _write(repo, [_row("aaaa000000000001", 10)], stats)
    _invoke(repo, "approve")
    rows = (repo / "data" / "tranche-approval-log.jsonl").read_text().splitlines()
    estimate = json.loads(rows[-1])["cost_estimate"]
    assert estimate["judge_label"] == label
    assert estimate["pages"] == 10
    assert estimate["partial"] is False
    assert estimate["cap_usd"] < estimate["high_usd"]
