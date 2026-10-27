"""The snapshot job's tranche-ready step (R7C.31), run by ``poll_snapshot.py``.

On a confirmed change, inside the page counter's ``fetch_and_count`` block:

1. Run ``tranche_diff.diff_tranches`` -- the classifier ``scripts/
   tranche_diff.py`` runs, in-process -- over the prior ``latest.json`` and
   the new manifest. New-side byte shas come from the page counter's
   already-fetched files; nothing is fetched twice.
2. For every rename/quarantine row, stage both sides' bytes in a temporary
   content-addressed dir: the new side copied from the page counter, the old
   side fetched credential-free from the old card's public ``asset_url`` and
   kept only if it hashes to the registry sha (``tranche_ready.old_bytes``).
3. Re-run the diff with that dir as its ``--bytes-dir``
   (``tranche_resave.bytes_dir_check``), so the committed receipt carries the
   same byte evidence an operator run with ``--bytes-dir`` would.
4. Build the record. (``_tranche_ready_run.publish`` validates it and
   writes both outputs.)

The bytes live in temp dirs that are gone when the job step ends; nothing
under the repository ever holds a PDF.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from _tranche_ready_supersedes import derive_supersedes
from r2_archive_assets import load_registry
from tranche_diff import diff_tranches

from pursue_index.config import settings
from pursue_index.release.rates import JudgeRate
from pursue_index.scrape.pdf_pages import FetchedPdfs
from pursue_index.tranche_manifest import display_rows_by_card_id
from pursue_index.tranche_ready import candidates as cands
from pursue_index.tranche_ready.old_bytes import StagedBytes, stage_new, stage_old
from pursue_index.tranche_ready.record import RecordInputs, build_record
from pursue_index.tranche_resave import bytes_dir_check

TOOL, VERSION = "poll_snapshot.py", "r7c31"


@dataclass(frozen=True)
class JobConfig:
    """Where the job reads its inputs and writes its two outputs."""

    ready_dir: Path
    diff_dir: Path
    registry: Path
    poll_state: Path
    csv_archive: Path
    tranche_issue: int | None = None
    poll_run_id: int | None = None
    poll_commit: str | None = None


def _sha_lookup(new_manifest: dict, fetched: FetchedPdfs) -> Callable[[str], str | None]:
    """``asset_url -> byte sha`` over the page counter's files only."""
    by_url = {}
    for cid, row in display_rows_by_card_id(new_manifest.get("cards", [])).items():
        path = fetched.paths.get(cid)
        if path is not None and row.get("asset_url"):
            by_url[row["asset_url"]] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return by_url.get


def _stage(diff: dict, old_by_id: dict, registry: dict, fetched: FetchedPdfs,
           bytes_dir: Path) -> tuple[dict[str, StagedBytes], dict[str, StagedBytes]]:
    """Both sides for every candidate row (old: every matched card)."""
    old_ids: list[str] = []
    for row in cands.candidate_rows(diff):
        old_ids += [row.old_card_id] if row.old_card_id else []
        old_ids += [m for m in row.row.get("matched_against") or [] if m not in old_ids]
    new = {r.new_card_id: stage_new(fetched.paths.get(r.new_card_id), bytes_dir)
           for r in cands.candidate_rows(diff)}
    old = {}
    for oid in dict.fromkeys(old_ids):
        rows = registry.get(oid) or []
        old[oid] = stage_old((old_by_id.get(oid) or {}).get("asset_url"),
                             rows[-1].get("byte_sha256") if rows else None, bytes_dir)
    return old, new


def _candidates(diff: dict, old_by_id: dict, old: dict, new: dict) -> list[dict]:
    missing = StagedBytes(path=None, failure="old_fetch_failed")
    return [
        cands.build_candidate(
            r, old_title=(old_by_id.get(r.old_card_id) or {}).get("title"),
            old_side=old.get(r.old_card_id, missing), new_side=new[r.new_card_id])
        for r in cands.candidate_rows(diff)
    ]


def _classify(old_m: dict, new_m: dict, cfg: JobConfig, fetched: FetchedPdfs) -> tuple:
    registry = load_registry(cfg.registry)
    old_by_id = display_rows_by_card_id(old_m.get("cards", []))
    sha_of = _sha_lookup(new_m, fetched)
    first = diff_tranches(old_m, new_m, registry, fetch_byte_sha=sha_of)
    with tempfile.TemporaryDirectory(prefix="pursue-tranche-bytes-") as tmp:
        old, new = _stage(first, old_by_id, registry, fetched, Path(tmp))
        diff = diff_tranches(old_m, new_m, registry, fetch_byte_sha=sha_of,
                             resave_check=bytes_dir_check(Path(tmp), registry),
                             move_resaves=settings.ingest_auto_approve_metadata_resaves)
        candidates = _candidates(diff, old_by_id, old, new)
    used_old = {c["old_card_id"] for c in candidates if c["old_card_id"] in old}
    failures = [(oid, old[oid].failure) for oid in sorted(used_old) if old[oid].failure]
    return diff, candidates, len(used_old) - len(failures), failures


def build(raw_new: dict, old_m: dict, cfg: JobConfig, fetched: FetchedPdfs,
          judge: JudgeRate | None, new_manifest_path: Path) -> tuple[dict, dict]:
    """``(diff, record)`` for the detected change; nothing written."""
    diff, candidates, old_fetched, old_failures = _classify(old_m, raw_new, cfg, fetched)
    record = build_record(RecordInputs(
        old_manifest=old_m, new_manifest=raw_new, diff=diff, candidates=candidates,
        page_counts=fetched.page_counts, new_fallback_ids=fetched.fallback_card_ids,
        old_fetched=old_fetched, old_failures=old_failures, judge=judge,
        tranche_issue=cfg.tranche_issue,
        supersedes=derive_supersedes(cfg.poll_state, cfg.csv_archive, old_m.get("csv_sha256"),
                                     raw_new["csv_sha256"], new_manifest_path, cfg.ready_dir),
        generated_by={"tool": TOOL, "version": VERSION, "poll_run_id": cfg.poll_run_id,
                      "poll_commit": cfg.poll_commit},
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    ))
    return diff, record

