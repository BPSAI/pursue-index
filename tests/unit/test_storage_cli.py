"""`pursue storage verify` — thin CLI over verify_storage_contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.config import settings

runner = CliRunner()

_OK_ENV = {
    "PURSUE_DATA_ROOT": "/srv/pursue-data",
    "R2_ACCOUNT_ID": "acct-primary",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",
    "BACKUP_R2_ACCOUNT_ID": "acct-backup",
    "BACKUP_R2_ACCESS_KEY_ID": "bak",
    "BACKUP_R2_SECRET_ACCESS_KEY": "bsk",
    "BACKUP_R2_BUCKET": "pursue-pdfs-backup",
}


def test_verify_exit_zero_when_all_tiers_configured(monkeypatch) -> None:
    for k, v in _OK_ENV.items():
        monkeypatch.setenv(k, v)
    res = runner.invoke(app, ["storage", "verify"])
    assert res.exit_code == 0, res.output
    assert "pursue-pdfs-backup" in res.output


def test_verify_exit_nonzero_when_backup_tier_missing(monkeypatch) -> None:
    for k, v in _OK_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BACKUP_R2_ACCESS_KEY_ID", raising=False)
    res = runner.invoke(app, ["storage", "verify"])
    assert res.exit_code == 1, res.output
    assert "MISSING" in res.output


def test_verify_warns_on_same_account_backup(monkeypatch) -> None:
    for k, v in _OK_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("BACKUP_R2_ACCOUNT_ID", "acct-primary")
    res = runner.invoke(app, ["storage", "verify"])
    # Same-account is a warning, not a hard failure — still exit 0.
    assert res.exit_code == 0, res.output
    assert "WARNING" in res.output
    assert "not disaster recovery" in res.output.lower()


# --- PDF r2-mirror CLI (mirror-pdfs / verify-mirror) ---------------------

_PDF = b"%PDF-1.4 cli fixture\n%%EOF\n"
_PDF_SHA = hashlib.sha256(_PDF).hexdigest()


def _seed(root: Path, card_id: str) -> None:
    ocr = root / "ocr" / card_id
    ocr.mkdir(parents=True, exist_ok=True)
    (ocr / "meta.json").write_text(json.dumps({"pdf_sha256": _PDF_SHA}))
    pdfs = root / "pdfs" / card_id
    pdfs.mkdir(parents=True, exist_ok=True)
    (pdfs / "doc.pdf").write_bytes(_PDF)


def _worklist(root: Path, *card_ids: str) -> Path:
    wl = root / "worklist.txt"
    wl.write_text("# tranche worklist\n" + "\n".join(card_ids) + "\n")
    return wl


def test_mirror_pdfs_then_verify_mirror_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_root", tmp_path)
    _seed(tmp_path, "cardA")
    wl = _worklist(tmp_path, "cardA")

    m = runner.invoke(app, ["storage", "mirror-pdfs", "--worklist", str(wl)])
    assert m.exit_code == 0, m.output
    assert (tmp_path / "r2-mirror" / "archive" / f"{_PDF_SHA}.pdf").is_file()

    v = runner.invoke(app, ["storage", "verify-mirror", "--worklist", str(wl)])
    assert v.exit_code == 0, v.output


def test_verify_mirror_exit_nonzero_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_root", tmp_path)
    _seed(tmp_path, "cardA")  # OCR ran, but mirror never staged
    wl = _worklist(tmp_path, "cardA")
    v = runner.invoke(app, ["storage", "verify-mirror", "--worklist", str(wl)])
    assert v.exit_code == 1, v.output
    assert "MISSING" in v.output
