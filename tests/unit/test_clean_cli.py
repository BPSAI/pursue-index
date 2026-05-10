"""Smoke tests for the ``pursue clean run`` CLI command.

Mocks the runner so we test argv parsing + manifest filtering, not the
HTTP layer (covered by test_clean_client.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.clean_cli import clean_app
from pursue_index.clean import runner as clean_runner

runner_cli = CliRunner()

# After vaivora P2 #1: ``clean_app`` now has a no-op callback, matching
# ``ops_cli``. This forces typer to keep the sub-app as a multi-command
# group regardless of how it's invoked, so the ``run`` token is now
# required in test invocations as well as in production
# (``pursue clean run ...``).


def _write_manifest(path: Path, card_ids: list[str]) -> None:
    """Write a minimal manifest with one PDF card per id."""
    cards = [
        {
            "card_id": cid,
            "title": f"card {cid}",
            "agency": "FBI",
            "asset_type": "PDF",
            "asset_url": f"https://example.test/{cid}.pdf",
            "release_date": "2025-01-01",
            "redacted": False,
            "raw": {},
        }
        for cid in card_ids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "source_url": "https://example.test/x.csv",
        "fetched_at": "2026-05-09T00:00:00Z",
        "csv_sha256": "0" * 64,
        "cards": cards,
    }))


def _seed_pages(ocr_root: Path, card_id: str, pages: list[dict]) -> None:
    """Write a fake pages.jsonl + meta.json for ``card_id`` under ``ocr_root``."""
    card_dir = ocr_root / card_id
    card_dir.mkdir(parents=True, exist_ok=True)
    (card_dir / "meta.json").write_text(
        json.dumps({"status": "ok", "card_id": card_id})
    )
    with (card_dir / "pages.jsonl").open("w") as fh:
        for p in pages:
            fh.write(json.dumps(p) + "\n")


@pytest.fixture(autouse=True)
def _patch_runner(monkeypatch: pytest.MonkeyPatch):
    """Stub run_card so CLI tests never hit the network."""
    calls: list[dict] = []

    def fake_run_card(**kwargs):
        calls.append(kwargs)
        return clean_runner.CardReport(
            card_id=kwargs["card_id"],
            pages_cleaned=1,
            pages_skipped=0,
            cost_usd=0.001,
            input_tokens=100,
            output_tokens=80,
            cache_read_tokens=0,
        )

    monkeypatch.setattr("pursue_index.cli.clean_cli.run_card", fake_run_card)
    return calls


def test_clean_run_drives_all_cards_when_no_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_runner,
) -> None:
    """No --cards / --limit → run every card in the manifest."""
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ["c1", "c2"])
    _seed_pages(tmp_path / "ocr", "c1", [{"page": 1, "text": "x"}])
    _seed_pages(tmp_path / "ocr", "c2", [{"page": 1, "text": "y"}])

    result = runner_cli.invoke(
        clean_app,
        ["run", "--manifest", str(manifest_path), "--budget-usd", "5"],
    )
    assert result.exit_code == 0, result.stdout
    card_ids = [c["card_id"] for c in _patch_runner]
    assert sorted(card_ids) == ["c1", "c2"]


def test_clean_run_filters_to_explicit_card_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_runner,
) -> None:
    """--cards c1,c3 → only those two run."""
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ["c1", "c2", "c3"])
    for cid in ("c1", "c2", "c3"):
        _seed_pages(tmp_path / "ocr", cid, [{"page": 1, "text": cid}])

    result = runner_cli.invoke(
        clean_app,
        ["run", "--manifest", str(manifest_path),
         "--cards", "c1,c3", "--budget-usd", "5"],
    )
    assert result.exit_code == 0, result.stdout
    assert sorted(c["card_id"] for c in _patch_runner) == ["c1", "c3"]


def test_clean_run_honors_limit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_runner,
) -> None:
    """--limit 2 → run at most two cards (deterministic by manifest order)."""
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ["a", "b", "c", "d"])
    for cid in ("a", "b", "c", "d"):
        _seed_pages(tmp_path / "ocr", cid, [{"page": 1, "text": cid}])

    result = runner_cli.invoke(
        clean_app,
        ["run", "--manifest", str(manifest_path),
         "--limit", "2", "--budget-usd", "5"],
    )
    assert result.exit_code == 0, result.stdout
    assert len(_patch_runner) == 2


def test_clean_run_exits_with_code_2_when_runner_raises_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """nayru P2 #5: when the runner raises BudgetExceededError mid-card,
    the CLI must exit 2 (distinct from runtime error code 1) AND print
    the partial summary so the operator sees what was spent before the
    abort. Previously we trusted the implementation; now there's a
    regression test pinning the exit-code contract.
    """
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ["c1", "c2"])
    _seed_pages(tmp_path / "ocr", "c1", [{"page": 1, "text": "x"}])
    _seed_pages(tmp_path / "ocr", "c2", [{"page": 1, "text": "y"}])

    def fake_run_card(**kwargs):
        if kwargs["card_id"] == "c1":
            return clean_runner.CardReport(
                card_id="c1", pages_cleaned=1, pages_skipped=0,
                cost_usd=0.42, input_tokens=100, output_tokens=80,
                cache_read_tokens=0,
            )
        # Second card trips the budget cap.
        raise clean_runner.BudgetExceededError(
            "Cost cap $0.50 exceeded after page 1 of card c2"
        )

    monkeypatch.setattr("pursue_index.cli.clean_cli.run_card", fake_run_card)

    result = runner_cli.invoke(
        clean_app,
        ["run", "--manifest", str(manifest_path), "--budget-usd", "0.50"],
    )
    assert result.exit_code == 2, result.stdout
    # Partial summary surfaces the c1 row + the budget message.
    assert "BUDGET EXCEEDED" in result.stdout
    assert "c1" in result.stdout


def test_clean_run_dry_run_does_not_invoke_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _patch_runner,
) -> None:
    """--dry-run prints the plan but never calls run_card."""
    from pursue_index.config import settings
    monkeypatch.setattr(settings, "data_root", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, ["c1"])
    _seed_pages(tmp_path / "ocr", "c1", [{"page": 1, "text": "x"}])

    result = runner_cli.invoke(
        clean_app,
        ["run", "--manifest", str(manifest_path), "--dry-run", "--budget-usd", "5"],
    )
    assert result.exit_code == 0, result.stdout
    assert _patch_runner == []
