"""Ingest-run orchestrator (plan step 7).

After `pursue ingest approve` clears the gate, `pursue ingest run`
promotes the candidate manifest snapshot to `data/manifests/latest.json`
and reports which downstream stages need to execute against the new
state. Heavy lifting (download/ocr/embed) stays under the existing
`pursue download`, `pursue ocr`, `pursue embed` CLI surfaces — this
orchestrator's job is to identify what's actually needed for *this*
tranche, not to re-implement the per-stage logic.

The motivating insight: most tranches will be mostly metadata-only
(title-format renames, description tweaks, pairing updates) and need
nothing more than manifest promotion + deploy-mirror rebuilds. The
expensive stages only fire when there's genuinely-new content (Class
B) to fetch, OCR, and embed.

Decision matrix (per tranche-diff classification):

  Class A renames        → no work (bytes already archived under old card_id)
  restored_unchanged     → no work (bytes already archived; pinned)
  restored_modified      → operator inspection required (NOT auto-OCR'd)
  Class C operator_manual → no work (metadata-only PR/VID cards)
  Class B (new_content)  → download → ocr → embed for each card with asset_url
                           (cards without asset_url, e.g. metadata-only entries,
                           still get manifest promotion but no pipeline stages)
  field_only_changes     → no work (metadata refresh only; rebuild mirrors)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def locate_snapshot(tranche_sha: str, snapshots_dir: Path) -> Path | None:
    """Find the snapshot manifest for the given (full or prefix) sha."""
    if not snapshots_dir.exists():
        return None
    for path in snapshots_dir.glob(f"{tranche_sha}*.json"):
        return path
    return None


def _mirror_snapshot_to_web(
    snapshot_path: Path,
    snapshot_sha: str,
    web_snapshots_dir: Path,
) -> None:
    """Copy the snapshot file into web/public/data/snapshots/ and refresh
    the index.json the /diff page reads. Safe filesystem-only operation;
    no external deps required."""
    if not web_snapshots_dir.exists():
        return
    target = web_snapshots_dir / f"{snapshot_sha}.json"
    shutil.copyfile(snapshot_path, target)
    # Rebuild the index from the on-disk listing so any prior snapshot
    # added through other means (operator manual copy, hot-fix) stays
    # in the listing.
    files = sorted(
        f.name for f in web_snapshots_dir.glob("*.json") if f.name != "index.json"
    )
    # Order entries by csv `fetched_at` so /diff shows oldest → newest
    # (matches the pipeline-side index.json convention).
    entries: list[tuple[str, str]] = []
    for fname in files:
        try:
            data = json.loads((web_snapshots_dir / fname).read_text())
            entries.append((data.get("fetched_at") or "", fname))
        except Exception:
            entries.append(("", fname))
    entries.sort()
    listing = [name for _, name in entries]
    (web_snapshots_dir / "index.json").write_text(
        json.dumps(listing, indent=2) + "\n"
    )


def promote_snapshot(snapshot_path: Path, manifest_path: Path) -> None:
    """Copy the snapshot to every deployed-side surface that depends on it.

    Three surfaces refresh in lockstep:

      1. `data/manifests/latest.json` — pipeline source-of-truth (the
         file the operator-CLI commands read).
      2. `web/src/data/manifest.json` — Astro build input (every card
         page is generated from this; drift here causes prod 404s).
      3. `web/public/data/snapshots/<sha>.json` + `index.json` — the
         `/diff` page reads these to compute the per-card delta against
         the prior snapshot. Without the new snapshot mirrored, /diff
         compares against an outdated baseline.

    All three caught and fixed manually on 2026-05-12 evening. The
    pattern was: `pursue ingest run` only updated #1; the operator
    discovered each missing mirror through prod-side symptoms (404s,
    missing thumbs, stale /diff). This function now updates all three
    atomically so a future ingest can't silently desync.

    NOT auto-invoked here (operator-local dependencies):
      - `build_video_posters.py` — needs operator's .mp4 files; if
        card_ids changed via rename, posters keyed under old card_ids
        need re-keying. Operator runs locally after a rename-heavy
        tranche.
      - `build_pdf_thumbs.py` — needs PDFs on the NAS; idempotent so
        running it after every ingest is cheap (only new/changed cards
        regenerate). Operator runs locally.
      - `build_search_data.py`, `build_atlas_layout.py`,
        `build_embed_data.py` — derived from pages.json + embeddings.bin
        which only change when OCR/embed stages run.

    The follow-up plan in `pursue-opsec/findings/2026-05-12-release-pipeline-gate.md`
    proposes a deterministic checklist + GitHub Action to cover ALL of
    the above as gated AC before any deploy.
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(snapshot_path, manifest_path)
    repo_root = manifest_path.parent.parent.parent
    _mirror_to_deploy_surfaces(snapshot_path, repo_root)


def _mirror_to_deploy_surfaces(snapshot_path: Path, repo_root: Path) -> None:
    """Walk every deploy-side surface that depends on the manifest. Each
    is independently checked so non-Astro / fresh-checkout layouts still
    work without raising."""
    build_manifest = repo_root / "web" / "src" / "data" / "manifest.json"
    if build_manifest.parent.exists():
        shutil.copyfile(snapshot_path, build_manifest)
    try:
        snapshot_sha = json.loads(snapshot_path.read_text()).get("csv_sha256", "")
    except (json.JSONDecodeError, OSError):
        snapshot_sha = ""
    if snapshot_sha:
        web_snapshots = repo_root / "web" / "public" / "data" / "snapshots"
        _mirror_snapshot_to_web(snapshot_path, snapshot_sha, web_snapshots)


def summarize_ingest_work(diff: dict[str, Any]) -> dict[str, Any]:
    """Identify which downstream stages need to run for this tranche.

    Returns a dict with:
      - needs_download: [card_id, ...] — Class B cards with asset_url
      - needs_ocr: [card_id, ...] — same set (OCR depends on downloaded bytes)
      - needs_embed: [card_id, ...] — same set (embed depends on OCR'd text)
      - needs_inspection: [card_id, ...] — restored_modified entries
      - metadata_only: bool — True when all the lists above are empty
    """
    needs_download: list[str] = []
    for r in diff.get("new_content", []) or []:
        if r.get("asset_url"):
            needs_download.append(r["new_card_id"])
    # OCR and embed follow the same set: each requires the prior stage's
    # output, all driven by the same "downloaded a new asset" trigger.
    needs_ocr = list(needs_download)
    needs_embed = list(needs_download)
    needs_inspection: list[str] = [
        r["new_card_id"] for r in diff.get("restored_modified", []) or []
    ]
    metadata_only = not (
        needs_download or needs_ocr or needs_embed or needs_inspection
    )
    return {
        "needs_download": needs_download,
        "needs_ocr": needs_ocr,
        "needs_embed": needs_embed,
        "needs_inspection": needs_inspection,
        "metadata_only": metadata_only,
    }


def render_next_steps(summary: dict[str, Any]) -> str:
    """Operator-facing instructions: what to run next, in order."""
    lines: list[str] = []
    if summary["metadata_only"]:
        lines.append(
            "Metadata-only tranche. No download/OCR/embed work needed. "
            "Rebuild deploy mirrors if any field-only changes affect them:"
        )
        lines.append("  cd web && npm run build")
        return "\n".join(lines)
    if summary["needs_download"]:
        ids = " ".join(summary["needs_download"])
        lines.append("New content detected — run the full pipeline against the new manifest:")
        lines.append(f"  pursue download run --manifest data/manifests/latest.json")
        lines.append(f"  pursue ocr run --manifest data/manifests/latest.json --engine auto")
        lines.append(f"  pursue embed run --manifest data/manifests/latest.json")
        lines.append(f"  # Affected card_ids: {ids}")
    if summary["needs_inspection"]:
        ids = " ".join(summary["needs_inspection"])
        lines.append("")
        lines.append("Restored-modified cards detected — manual inspection required before re-OCR:")
        for cid in summary["needs_inspection"]:
            lines.append(f"  - {cid}: compare archived bytes vs upstream bytes; decide whether to accept or reject")
    return "\n".join(lines)
