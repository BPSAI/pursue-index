"""The client is built before anything is reserved, metered or written.

A missing SDK or key must fail the run with nothing charged. An error after a
request may have been sent keeps its conservative reservation, as before. No
test spends: the SDK import and key are faked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.vision import client, spend
from pursue_index.vision.eligibility import EligibleItem
from pursue_index.vision.run import ESTIMATED_COST_PER_CALL_USD, run_vision
from tests.unit.test_vision_cli import _examination, _img_card, _write_manifest
from tests.unit.test_vision_redescribe import (  # noqa: F401  (autouse fixture)
    _assets_resolve,
    _worklist,
    _write_sidecar,
)

runner = CliRunner()
CARD = "a1a1a1a1a1a1a1a1"


@pytest.fixture
def reserves(monkeypatch) -> list[int]:
    seen: list[int] = []
    real = spend.SpendBudget.reserve

    def counting(self) -> None:
        seen.append(1)
        real(self)

    monkeypatch.setattr(spend.SpendBudget, "reserve", counting)
    return seen


@pytest.fixture
def no_sdk(monkeypatch) -> None:
    """examine_image is stubbed; the client factory is the real one, SDK missing."""
    import pursue_index.vision.render as render_mod

    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import raises ImportError
    monkeypatch.setattr(client, "examine_image", _examination)
    monkeypatch.setattr(render_mod, "load_image_for", lambda item, **kw: item)
    monkeypatch.delenv("CI", raising=False)


def _argv(tmp_path: Path, *flags: str) -> list[str]:
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card(CARD)])
    return ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"), *flags]


def test_a_missing_sdk_is_a_clear_error_from_the_factory(monkeypatch) -> None:
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(client.VisionClientError, match="anthropic"):
        client.require_client()


def test_a_missing_key_is_a_clear_error_from_the_factory(monkeypatch) -> None:
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setattr("pursue_index.config.credentials.anthropic_api_key", lambda: None)
    with pytest.raises(client.VisionClientError, match="ANTHROPIC_API_KEY"):
        client.require_client()


@pytest.mark.parametrize("flags", [["--run"], ["--live", "--confirm-live", "--budget-usd", "1"],
                                   ["--live-smoke", CARD]])
def test_fresh_paths_fail_before_any_reservation(tmp_path, no_sdk, reserves, flags) -> None:
    result = runner.invoke(app, _argv(tmp_path, *flags))
    assert result.exit_code != 0
    assert reserves == []
    assert "anthropic" in result.output.lower()
    assert "$0.0" not in result.output or "metered" not in result.output
    assert not (tmp_path / "o" / f"{CARD}.json").exists()


def test_redescribe_fails_before_any_reservation_and_leaves_files(
    tmp_path, no_sdk, reserves
) -> None:
    _write_sidecar(tmp_path / "o", CARD)
    before = (tmp_path / "o" / f"{CARD}.json").read_text("utf-8")
    args = _argv(tmp_path, "--redescribe", "--worklist", str(_worklist(tmp_path, [CARD])),
                 "--budget-usd", "3", "--confirm-live")
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert reserves == []
    assert "anthropic" in result.output.lower()
    assert "vision spend" not in result.output
    assert (tmp_path / "o" / f"{CARD}.json").read_text("utf-8") == before


def test_preflight_needs_no_client(tmp_path, no_sdk, reserves) -> None:
    _write_sidecar(tmp_path / "o", CARD)
    args = _argv(tmp_path, "--redescribe", "--worklist", str(_worklist(tmp_path, [CARD])),
                 "--budget-usd", "3")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def test_a_call_that_raises_keeps_its_reservation(tmp_path) -> None:
    def boom(_img: object) -> dict:
        raise RuntimeError("connection reset after the request was sent")

    item = EligibleItem(card_id=CARD, page=1, kind="img_card",
                        image_path=Path("/tmp/x"), title="T", row_key="")
    report = run_vision([item], tmp_path, examine_fn=boom, load_image_fn=lambda i: i,
                        budget_usd=1.0)
    assert report.spent_usd == pytest.approx(ESTIMATED_COST_PER_CALL_USD)
    assert json.dumps(report.failures)


def test_any_key_lookup_failure_is_a_client_error_without_the_value(monkeypatch) -> None:
    monkeypatch.setattr(client, "_client", None)
    monkeypatch.setitem(sys.modules, "anthropic", type(sys)("anthropic"))

    def boom() -> str:
        raise ValueError("bad value sk-ant-SECRET123")

    monkeypatch.setattr("pursue_index.config.credentials.anthropic_api_key", boom)
    with pytest.raises(client.VisionClientError) as info:
        client.require_client()
    assert "ANTHROPIC_API_KEY" in str(info.value)
    assert "SECRET123" not in str(info.value)
    assert info.value.__cause__ is None or "SECRET123" not in str(info.value.__cause__)
