"""`pursue storage verify` — thin CLI over verify_storage_contract."""

from __future__ import annotations

from typer.testing import CliRunner

from pursue_index.cli.commands import app

runner = CliRunner()

_OK_ENV = {
    "PURSUE_DATA_ROOT": "/mnt/nas/personal/pursue",
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
