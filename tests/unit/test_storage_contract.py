"""Storage-contract codification tests (never-again turnkey/storage task).

Codifies the durability contract in code (not memory notes): every archived
asset must land in three tiers — NAS (``PURSUE_DATA_ROOT``), the main R2 bucket
(``pursue-pdfs``), and the backup R2 bucket (``pursue-pdfs-backup``). The
``verify_storage_contract`` preflight checks all three are configured and
surfaces the same-CF-account backup risk (not true DR).
"""

from __future__ import annotations

from pursue_index.storage.contract import (
    BACKUP_R2_BUCKET,
    MAIN_R2_BUCKET,
    STORAGE_CONTRACT,
    verify_storage_contract,
)


def _full_env(*, same_account: bool = True) -> dict[str, str]:
    backup_acct = "acct-primary" if same_account else "acct-backup"
    return {
        "PURSUE_DATA_ROOT": "/mnt/nas/personal/pursue",
        "R2_ACCOUNT_ID": "acct-primary",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
        "BACKUP_R2_ACCOUNT_ID": backup_acct,
        "BACKUP_R2_ACCESS_KEY_ID": "bak",
        "BACKUP_R2_SECRET_ACCESS_KEY": "bsk",
        "BACKUP_R2_BUCKET": "pursue-pdfs-backup",
    }


def test_contract_defines_three_tiers_with_writer_stages() -> None:
    names = [t.name for t in STORAGE_CONTRACT]
    assert names == ["nas", "r2_primary", "r2_backup"]
    # Each tier declares which pipeline stage writes it (codified, not a note).
    for tier in STORAGE_CONTRACT:
        assert tier.written_by, f"{tier.name} must name its writing stage"
    buckets = {t.name: t.bucket for t in STORAGE_CONTRACT}
    assert buckets["r2_primary"] == MAIN_R2_BUCKET == "pursue-pdfs"
    assert buckets["r2_backup"] == BACKUP_R2_BUCKET == "pursue-pdfs-backup"
    assert buckets["nas"] is None  # NAS is a filesystem root, not a bucket


def test_verify_ok_when_all_three_tiers_configured() -> None:
    result = verify_storage_contract(_full_env(same_account=False))
    assert result.ok is True
    assert result.missing == {}
    assert result.same_account_backup is False


def test_verify_flags_missing_backup_tier() -> None:
    env = _full_env()
    del env["BACKUP_R2_ACCESS_KEY_ID"]
    del env["BACKUP_R2_SECRET_ACCESS_KEY"]
    result = verify_storage_contract(env)
    assert result.ok is False
    assert "r2_backup" in result.missing
    assert "BACKUP_R2_ACCESS_KEY_ID" in result.missing["r2_backup"]
    # A missing backup tier means the third-copy durability guarantee is unmet.
    assert any("backup" in w.lower() for w in result.warnings)


def test_verify_flags_missing_nas_root() -> None:
    env = _full_env()
    del env["PURSUE_DATA_ROOT"]
    result = verify_storage_contract(env)
    assert result.ok is False
    assert result.missing.get("nas") == ["PURSUE_DATA_ROOT"]


def test_verify_surfaces_same_account_backup_risk() -> None:
    """The documented finding: backup is the SAME CF account, so it is not DR."""
    result = verify_storage_contract(_full_env(same_account=True))
    # Configured, so ok — but the same-account risk is surfaced as a warning.
    assert result.ok is True
    assert result.same_account_backup is True
    assert any(
        "same" in w.lower() and "account" in w.lower() for w in result.warnings
    ), result.warnings


def test_verify_primary_account_falls_back_to_cf_account_id() -> None:
    env = _full_env(same_account=True)
    del env["R2_ACCOUNT_ID"]
    env["PURSUE_CF_ACCOUNT_ID"] = "acct-primary"
    result = verify_storage_contract(env)
    assert result.ok is True
    assert result.same_account_backup is True
