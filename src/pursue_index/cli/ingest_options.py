"""Typer options shared by ``pursue ingest`` commands.

Split out of ``ingest_cli`` to keep it under the arch limits. Data-path
defaults resolve when the command runs (see ``ingest_defaults``).
"""

from __future__ import annotations

import typer

from pursue_index.cli.ingest_defaults import _default

_OPT_APPROVE_RENAME = typer.Option(
    None,
    "--approve-rename",
    help="Repeatable. Format: <new_card_id>=<old_card_id>. Each flag promotes a Class C "
    "quarantined card into an operator_manual alias.",
)
_OPT_SKIP_AUDIT = typer.Option(
    False,
    "--skip-audit",
    help="Skip the TOCTOU re-fetch audit. NOT RECOMMENDED. Requires --reason, which is "
    "recorded on the approval row.",
)
_OPT_FROM_DIFF_COST_CAP = typer.Option(
    None,
    "--cost-cap-usd",
    help="With --from-diff: override the embed stage cost cap (USD) so a large "
    "tranche isn't blocked at the default cap. Omit to use the embed default.",
)
_OPT_FROM_DIFF = typer.Option(
    False,
    "--from-diff",
    help="One-command path: export the scoped work-list from the tranche-diff "
    "and run the scoped download -> ocr -> embed stages via --worklist.",
)
_OPT_DRY_RUN = typer.Option(
    False,
    "--dry-run",
    help="With --from-diff: print the work-list (the card_ids that would be "
    "OCR'd/embedded) WITHOUT running any stage or spending budget.",
)
_OPT_RUN_LOG = typer.Option(_default("DEFAULT_APPROVAL_LOG"), "--log")
_OPT_RUN_SNAPSHOTS_DIR = typer.Option(_default("DEFAULT_MANIFEST_SNAPSHOTS"), "--snapshots-dir")
_OPT_DATE_RESOLUTIONS = typer.Option(
    None, "--date-resolutions",
    help="Manual date-resolution overlay; picks the snapshot variant made with it. "
         "Default: data/date_resolutions.json of the checkout --snapshots-dir is in "
         "(refused for a --snapshots-dir outside the standard layout).",
)
_OPT_RUN_MANIFEST = typer.Option(_default("DEFAULT_LATEST_MANIFEST"), "--manifest")
_OPT_RUN_DIFF_DIR = typer.Option(_default("DEFAULT_DIFF_DIR"), "--diff-dir")
_OPT_RUN_ALIASES = typer.Option(
    _default("DEFAULT_ALIASES"), "--aliases",
    help="With --from-diff: card-aliases.json, to scope this tranche's approved renames.",
)
_OPT_RUN_ASSET_REGISTRY = typer.Option(
    _default("DEFAULT_ASSET_REGISTRY"), "--asset-registry",
    help="With --from-diff: asset-bytes-registry.jsonl, to detect bytes-changed cards.",
)
_OPT_RUN_ENGINE = typer.Option(
    None, "--engine", help="With --from-diff: OCR engine passthrough (operated: llm-dots)."
)
_OPT_RUN_FORCE = typer.Option(
    False, "--force", help="With --from-diff: force re-OCR (overwrite status=ok)."
)
_OPT_RUN_CONCURRENCY = typer.Option(
    None, "--concurrency", help="With --from-diff: OCR concurrency passthrough (operated: 8)."
)
_OPT_APPROVE_LOG = typer.Option(_default("DEFAULT_APPROVAL_LOG"), "--log")
_OPT_APPROVE_ALIASES = typer.Option(_default("DEFAULT_ALIASES"), "--aliases")
_OPT_APPROVE_DIFF_DIR = typer.Option(_default("DEFAULT_DIFF_DIR"), "--diff-dir")
_OPT_APPROVE_SNAPSHOTS_DIR = typer.Option(_default("DEFAULT_MANIFEST_SNAPSHOTS"), "--snapshots-dir")
_OPT_WORKLIST_OUT = typer.Option(
    _default("DEFAULT_WORKLIST"),
    "--worklist",
    help="Where --from-diff writes the scoped card_id list the executors read.",
)
_OPT_ALLOW_BEHIND = typer.Option(
    False,
    "--allow-behind",
    help="Proceed even though this checkout is behind origin/main on poll-written "
    "paths. Requires --reason (12+ characters); recorded as an audited exception.",
)
_OPT_BEHIND_REASON = typer.Option(
    None,
    "--reason",
    help="Required with --allow-behind (why it is safe to proceed behind the poller) and "
    "with --skip-audit (why the audit is skipped); 12+ characters, recorded.",
)
