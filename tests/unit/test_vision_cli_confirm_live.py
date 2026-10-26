"""``--live`` needs a second, explicit ``--confirm-live``.

The ``CI`` environment check only stops one kind of caller. Anything else that
can run the command (a cron entry, a script, a pasted command line) must also
say, in the invocation itself, that it means to spend.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from tests.unit.test_vision_cli import (
    _examination,
    _img_card,
    _patch_seams,
    _write_manifest,
)

runner = CliRunner()


def _invoke(tmp_path: Path, monkeypatch, extra: list[str]):
    calls: list[str] = []

    def examine(item, **kw) -> dict:
        calls.append("called")
        return _examination(item, **kw)

    _patch_seams(monkeypatch, examine)
    monkeypatch.delenv("CI", raising=False)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
         "--live", "--budget-usd", "1.0", *extra],
    )
    return result, calls


def test_live_without_confirm_live_is_refused_before_any_call(
    tmp_path: Path, monkeypatch
) -> None:
    result, calls = _invoke(tmp_path, monkeypatch, [])
    assert result.exit_code == 2
    assert calls == []
    assert "--confirm-live" in result.output


def test_live_with_confirm_live_runs(tmp_path: Path, monkeypatch) -> None:
    result, calls = _invoke(tmp_path, monkeypatch, ["--confirm-live"])
    assert result.exit_code == 0, result.output
    assert calls == ["called"]


def test_confirm_live_does_not_override_ci(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    _patch_seams(monkeypatch, lambda *a, **k: calls.append("called"))
    monkeypatch.setenv("CI", "true")
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, [_img_card("imgA")])
    result = runner.invoke(
        app,
        ["vision", "run", "--manifest", str(manifest), "--out", str(tmp_path / "o"),
         "--live", "--confirm-live", "--budget-usd", "1.0"],
    )
    assert result.exit_code == 2
    assert calls == []
