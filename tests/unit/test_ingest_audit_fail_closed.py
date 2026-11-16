"""The pre-approval audit fails closed when it tries to verify and can't.

`ingest approve` refuses (exit 3) on a missing snapshot, a missing curl_cffi,
any fetch failing, or a target that should have an asset_url lacking one.
Targets with no asset_url by design pass, labelled "nothing fetchable". The
label (or "skipped: <reason>" for `--skip-audit`) is recorded on the row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from pursue_index.cli import ingest_audit
from pursue_index.ingest import record_approval

SHA = "ab" * 32


@pytest.fixture
def snapshots(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / f"{SHA}.json").write_text(json.dumps({"cards": []}))
    return d


def _audit(snapshots: Path, *, tranche: str = SHA, skip: bool = False, reason: str | None = None):
    return ingest_audit._run_pre_approval_audit([], {}, tranche, snapshots, skip, reason)


def _exit_code(fn) -> int:
    with pytest.raises(typer.Exit) as exc:
        fn()
    return exc.value.exit_code


def _with_targets(monkeypatch: pytest.MonkeyPatch, statuses: list[str],
                  kind: str = "byte_collision_rename") -> None:
    # The fetcher is mocked, so the tests must not depend on curl_cffi being installed.
    monkeypatch.setattr(ingest_audit.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(ingest_audit, "collect_audit_targets",
                        lambda *a: [{"asset_url": "https://x"} for _ in statuses])
    monkeypatch.setattr(ingest_audit, "audit_targets", lambda targets, fetch: [
        {"status": s, "kind": kind, "card_id": "c"} for s in statuses])
    monkeypatch.setattr(ingest_audit, "render_audit_summary", lambda results: "")


def test_a_bad_tranche_is_a_usage_error(snapshots: Path) -> None:
    assert _exit_code(lambda: _audit(snapshots, tranche="ab*")) == 2
    assert _exit_code(lambda: _audit(snapshots, tranche="short")) == 2


def test_no_snapshot_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _exit_code(lambda: _audit(tmp_path)) == 3
    assert "no snapshot manifest" in capsys.readouterr().err


def test_missing_curl_cffi_refuses_by_name(snapshots: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    _with_targets(monkeypatch, ["ok"])
    monkeypatch.setattr(ingest_audit.importlib.util, "find_spec", lambda name: None)
    assert _exit_code(lambda: _audit(snapshots)) == 3
    assert "curl_cffi" in capsys.readouterr().err


def test_any_fetch_failing_refuses(snapshots: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_targets(monkeypatch, ["fetch_failed", "fetch_failed"])
    assert _exit_code(lambda: _audit(snapshots)) == 3
    _with_targets(monkeypatch, ["ok", "fetch_failed"])  # a mixed tranche stays strict
    assert _exit_code(lambda: _audit(snapshots)) == 3


def test_verified_and_nothing_to_audit_are_labelled(snapshots: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    _with_targets(monkeypatch, ["ok", "ok"])
    results, label = _audit(snapshots)
    assert len(results) == 2 and label == "verified (2 ok, 0 skipped by design)"
    _with_targets(monkeypatch, ["ok", "mismatch"], kind="operator_manual_rename")
    assert _audit(snapshots)[1].startswith("partly verified (1 ok, 1 not ok but non-blocking")
    _with_targets(monkeypatch, [])
    assert _audit(snapshots) == ([], "nothing to audit (no byte-changing targets)")


def test_all_skipped_by_design_passes_as_nothing_fetchable(
    snapshots: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _with_targets(monkeypatch, ["skipped", "skipped"], kind="operator_manual_rename")
    _, label = _audit(snapshots)
    assert label.startswith("nothing fetchable (2 skipped")
    assert label in capsys.readouterr().err


def test_a_skipped_target_that_should_have_a_url_is_a_data_defect(
    snapshots: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _with_targets(monkeypatch, ["skipped"], kind="restored_unchanged")
    assert _exit_code(lambda: _audit(snapshots)) == 3
    assert "restored_unchanged have no asset_url" in capsys.readouterr().err


def test_skip_audit_needs_a_reason(snapshots: Path) -> None:
    assert _exit_code(lambda: _audit(snapshots, skip=True)) == 2
    assert _exit_code(lambda: _audit(snapshots, skip=True, reason="too short")) == 2
    assert _audit(snapshots, skip=True, reason="  upstream down; bytes checked by hand  ") == (
        [], "skipped: upstream down; bytes checked by hand")


def test_the_audit_label_is_recorded_on_the_approval_row(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    record_approval(log, SHA, "n", {}, [], audit="skipped: upstream down; checked by hand")
    record_approval(log, SHA, "n", {}, [])
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["audit"] == "skipped: upstream down; checked by hand"
    assert "audit" not in rows[1]
