"""Codified storage-durability contract (never-again turnkey/storage task).

Operational truth about WHERE archived assets live must be executable, not a
memory note (the same drift class that caused the Release-4 fumble). This module
is the single source of truth for the three-tier archive contract and a
credential-free preflight that verifies all three tiers are configured.

The contract: every archived asset (PDF / IMG / A/V bytes) must land in
**three** tiers —

  1. ``nas``        — the operator's NAS mount (``PURSUE_DATA_ROOT``); the
                      download/ingest stage stages every asset here first.
  2. ``r2_primary`` — the main Cloudflare R2 bucket ``pursue-pdfs``; the
                      ingest/OCR upload stage content-addresses each asset to
                      ``archive/<sha>.<ext>`` plus a ``<card_id>.<ext>``
                      current-pointer here (this is the serving tier).
  3. ``r2_backup``  — the backup bucket ``pursue-pdfs-backup``; filled by the
                      opsec daily mirror cron (``mirror_to_backup.py``), NOT by
                      the inline ingest run.

KNOWN RISK (documented finding, surfaced by ``verify_storage_contract``): the
backup bucket is, as configured today, in the **same Cloudflare account** as the
primary. It protects against accidental object deletion / bucket-level mistakes
but is NOT disaster recovery — an account suspension, credential compromise, or
account deletion takes both tiers at once. True DR needs a separate account or a
different provider. This module reports the same-account state; it does NOT
change any bucket credential.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

MAIN_R2_BUCKET = "pursue-pdfs"
BACKUP_R2_BUCKET = "pursue-pdfs-backup"


@dataclass(frozen=True)
class StorageTier:
    """One durability tier + the env keys that configure it."""

    name: str
    display: str
    bucket: str | None  # None for the NAS filesystem tier
    written_by: str  # which pipeline stage writes this tier (codified)
    required_env: tuple[str, ...]


# Canonical three-tier contract. Order is durability order: NAS first (staged at
# download), primary R2 (serving), backup R2 (mirror cron). Each tier names the
# stage that writes it so the writer/tier map lives in code, not a runbook.
STORAGE_CONTRACT: tuple[StorageTier, ...] = (
    StorageTier(
        name="nas",
        display="NAS (PURSUE_DATA_ROOT)",
        bucket=None,
        written_by="download/ingest stage (stages every asset to NAS first)",
        required_env=("PURSUE_DATA_ROOT",),
    ),
    StorageTier(
        name="r2_primary",
        display=f"main R2 ({MAIN_R2_BUCKET})",
        bucket=MAIN_R2_BUCKET,
        written_by="ingest/OCR upload stage (archive/<sha> + <card_id> current-pointer)",
        required_env=("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"),
    ),
    StorageTier(
        name="r2_backup",
        display=f"backup R2 ({BACKUP_R2_BUCKET})",
        bucket=BACKUP_R2_BUCKET,
        written_by="opsec daily mirror cron (mirror_to_backup.py), not inline ingest",
        required_env=(
            "BACKUP_R2_ACCOUNT_ID",
            "BACKUP_R2_ACCESS_KEY_ID",
            "BACKUP_R2_SECRET_ACCESS_KEY",
        ),
    ),
)


@dataclass
class StorageVerifyResult:
    ok: bool
    missing: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    same_account_backup: bool = False


def _primary_account(env: Mapping[str, str]) -> str | None:
    return env.get("R2_ACCOUNT_ID") or env.get("PURSUE_CF_ACCOUNT_ID") or None


def verify_storage_contract(env: Mapping[str, str]) -> StorageVerifyResult:
    """Check all three tiers are configured; surface the same-account risk.

    Credential-free: only checks for the PRESENCE of the configuring env keys,
    never reads their secret values and never touches the network. ``ok`` is
    True iff every tier's required env keys resolve. The same-account backup
    state is reported as a warning (not an error) — it is a durability posture
    finding, not a misconfiguration that should block a release.
    """
    missing: dict[str, list[str]] = {}
    for tier in STORAGE_CONTRACT:
        absent = [k for k in tier.required_env if not env.get(k)]
        if absent:
            missing[tier.name] = absent

    warnings: list[str] = []
    if "r2_backup" in missing:
        warnings.append(
            "backup R2 tier is not fully configured — the third-copy durability "
            "guarantee is UNMET this run (mirror cron cannot write)."
        )

    primary_acct = _primary_account(env)
    backup_acct = env.get("BACKUP_R2_ACCOUNT_ID")
    same_account = bool(primary_acct) and primary_acct == backup_acct
    if same_account:
        warnings.append(
            "backup R2 is in the SAME Cloudflare account as primary "
            f"({primary_acct}). This is NOT disaster recovery: an account "
            "suspension/compromise/deletion takes both buckets. Recommendation: "
            "move the backup to a separate CF account or a different provider. "
            "Do not silently rotate bucket credentials — this needs an operator "
            "decision."
        )

    return StorageVerifyResult(
        ok=not missing,
        missing=missing,
        warnings=warnings,
        same_account_backup=same_account,
    )


def render_contract_summary(result: StorageVerifyResult) -> str:
    """Operator-facing markdown for the verify result (used by the CLI)."""
    lines = ["### Storage contract (3-tier durability)", ""]
    for tier in STORAGE_CONTRACT:
        absent = result.missing.get(tier.name, [])
        mark = "MISSING" if absent else "ok"
        detail = f" (missing: {', '.join(absent)})" if absent else ""
        lines.append(f"* `{tier.name}` — {tier.display} — {mark}{detail}")
        lines.append(f"    * written by: {tier.written_by}")
    lines.append("")
    lines.append(f"**All tiers configured:** {'yes' if result.ok else 'NO'}")
    for warn in result.warnings:
        lines.append(f"> WARNING: {warn}")
    return "\n".join(lines)
