"""Characterization tests for scripts/r2_reconcile.py main() (fakes only)."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import r2_reconcile  # noqa: E402

_WHEN = dt.datetime(2026, 5, 8, 12, 0, 0, tzinfo=dt.UTC)


class _FakeClient:
    def __init__(self, objects):
        self._objects = objects

    def list_objects_v2(self, **kwargs):
        return {
            "Contents": [
                {"Key": k, "Size": s, "LastModified": _WHEN, "ETag": '"e"'}
                for k, s in self._objects
            ],
            "IsTruncated": False,
        }


def _registry(tmp_path: Path) -> Path:
    p = tmp_path / "reg.jsonl"
    rows = [
        {"archive_key": "archive/aa", "current_key": "C1.pdf"},
        {"archive_key": "archive/bb", "current_key": ""},
        {"current_key": "C3.pdf"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    return p


def _run(monkeypatch, argv, client):
    monkeypatch.setattr(r2_reconcile, "make_r2_client", lambda: client)
    monkeypatch.setattr(sys, "argv", ["r2_reconcile.py", *argv])
    return r2_reconcile.main()


def test_no_client_returns_2(monkeypatch, tmp_path, capsys):
    assert _run(monkeypatch, ["--registry", str(_registry(tmp_path))], None) == 2
    assert capsys.readouterr().out == ""


def test_text_report(monkeypatch, tmp_path, capsys):
    client = _FakeClient(
        [("archive/aa", 10), ("C1.pdf", 2_000_000), ("orph/x.pdf", 3_000_000),
         ("archive/zz", 1), ("lone.pdf", 5)]
    )
    rc = _run(monkeypatch, ["--registry", str(_registry(tmp_path)), "--bucket", "b"], client)
    assert rc == 0
    out = capsys.readouterr().out
    assert out == (
        "=== R2 reconciliation: bucket=b ===\n"
        "Bucket objects:                  5\n"
        "Registry archive_keys:           2\n"
        "Registry current_keys:           2\n"
        "Registered (archive + current):  4\n"
        "\n"
        "In both bucket + registry:       2\n"
        "Missing from bucket (BAD if >0): 2\n"
        "Orphan in bucket:                3\n"
        "\n--- MISSING FROM BUCKET ---\n"
        "  C3.pdf\n"
        "  archive/bb\n"
        "\n--- ORPHAN OBJECTS (in bucket, not in registry) ---\n"
        "  archive/* (content-addressed)            1\n"
        "  <card_id>.<ext> (current-pointer)        1\n"
        "  orph/*                                   1\n"
        "\n"
        "Per-object listing:\n"
        f"  {'archive/zz':50s} {0.0:9.2f} MB   {_WHEN.isoformat()}\n"
        f"  {'lone.pdf':50s} {0.0:9.2f} MB   {_WHEN.isoformat()}\n"
        f"  {'orph/x.pdf':50s} {3.0:9.2f} MB   {_WHEN.isoformat()}\n"
    )


def test_text_report_clean_has_no_sections(monkeypatch, tmp_path, capsys):
    client = _FakeClient([("archive/aa", 1), ("archive/bb", 1), ("C1.pdf", 1), ("C3.pdf", 1)])
    assert _run(monkeypatch, ["--registry", str(_registry(tmp_path))], client) == 0
    out = capsys.readouterr().out
    assert "=== R2 reconciliation: bucket=pursue-pdfs ===" in out
    assert "MISSING" not in out and "ORPHAN" not in out


def test_json_report(monkeypatch, tmp_path, capsys):
    client = _FakeClient([("archive/aa", 10), ("orph/x.pdf", 7)])
    rc = _run(monkeypatch, ["--registry", str(_registry(tmp_path)), "--json"], client)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "bucket": "pursue-pdfs",
        "bucket_object_count": 2,
        "registry_archive_count": 2,
        "registry_current_count": 2,
        "in_both": 1,
        "missing_from_bucket": ["C1.pdf", "C3.pdf", "archive/bb"],
        "orphan_in_bucket": [
            {"key": "orph/x.pdf", "size": 7, "last_modified": _WHEN.isoformat()}
        ],
        "orphan_summary": {"orph/*": 1},
    }


def test_help_text(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["r2_reconcile.py", "--help"])
    with pytest.raises(SystemExit) as e:
        r2_reconcile.main()
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--bucket" in out and "--registry" in out and "--json" in out
    assert "machine-readable output" in out
