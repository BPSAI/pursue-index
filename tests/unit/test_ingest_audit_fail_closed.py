"""The pre-approval audit fails closed when it can verify nothing.

`ingest approve` refuses (exit 3) unless the audit verified something: a
missing snapshot, a missing curl_cffi, or every fetch failing all refuse.
`--skip-audit` bypasses it only with a `--reason`, recorded on the approval
row. A tranche with no byte-changing targets has nothing to verify and passes.
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


def _with_targets(monkeypatch: pytest.MonkeyPatch, statuses: list[str]) -> None:
    monkeypatch.setattr(ingest_audit, "collect_audit_targets", lambda *a: [{"x": i} for i in statuses])
    monkeypatch.setattr(ingest_audit, "audit_targets", lambda targets, fetch: [
        {"status": s, "kind": "byte_collision_rename", "card_id": "c"} for s in statuses])
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


def test_every_fetch_failing_refuses(snapshots: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_targets(monkeypatch, ["fetch_failed", "fetch_failed", "skipped"])
    assert _exit_code(lambda: _audit(snapshots)) == 3


def test_some_verified_or_nothing_to_verify_passes(snapshots: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    _with_targets(monkeypatch, ["ok", "fetch_failed"])
    results, skipped = _audit(snapshots)
    assert len(results) == 2 and skipped is None
    _with_targets(monkeypatch, [])
    assert _audit(snapshots) == ([], None)


def test_skip_audit_needs_a_reason(snapshots: Path) -> None:
    assert _exit_code(lambda: _audit(snapshots, skip=True)) == 2
    assert _exit_code(lambda: _audit(snapshots, skip=True, reason="too short")) == 2
    assert _audit(snapshots, skip=True, reason="  upstream down; bytes checked by hand  ") == (
        [], "upstream down; bytes checked by hand")


def test_the_skip_reason_is_recorded_on_the_approval_row(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    record_approval(log, SHA, "n", {}, [], audit_skip_reason="upstream down; checked by hand")
    record_approval(log, SHA, "n", {}, [])
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["audit_skipped"] == {"reason": "upstream down; checked by hand"}
    assert "audit_skipped" not in rows[1]
