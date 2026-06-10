"""Phase 1 snapshot rotation — keeps the /diff page current.

When the manifest's csv_sha256 differs from the latest snapshot in the
web-side index, rotate a snapshot file + index entry. Idempotent: if
the latest snapshot already matches current manifest sha, no-op.

This fixes the recurring gap where `pursue scrape run` would normally
do the rotation but operator-attended re-scrapes (using `parse_csv +
build_manifest` directly) bypass it.

Updates BOTH indexes:
- `data/manifests/snapshots/index.json` (pipeline-side, rich objects)
- `web/public/data/snapshots/index.json` (web-side, enriched
  {filename, fetched_at, card_count} objects the /diff page reads — the
  metadata lets the selectors label each snapshot without fetching it)

Also copies the snapshot file into both
`data/manifests/snapshots/<sha>.json` and
`web/public/data/snapshots/<sha>.json` (the public path is what the
DiffIsland fetches at runtime).

Usage::

    python scripts/runbook_snapshot_rotate.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Expose the src-layout package so the shared snapshot-index writer is
# importable when this runbook is invoked directly (matches the
# sys.path-injection pattern in scripts/poll_pursue.py).
sys.path.insert(0, str(_REPO_ROOT / "src"))
from pursue_index.scrape.snapshots import write_public_index  # noqa: E402

LATEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
SNAPSHOTS_PIPELINE = _REPO_ROOT / "data" / "manifests" / "snapshots"
SNAPSHOTS_WEB = _REPO_ROOT / "web" / "public" / "data" / "snapshots"


def _load_manifest() -> dict:
    return json.loads(LATEST.read_text())


def _current_sha(manifest: dict) -> str:
    return manifest["csv_sha256"]


def _pipeline_index_load() -> dict:
    p = SNAPSHOTS_PIPELINE / "index.json"
    if not p.exists():
        return {"snapshots": []}
    return json.loads(p.read_text())


def _web_index_load() -> list[str]:
    """Return web-index filenames, tolerant of both the legacy bare-string
    list and the enriched {filename, ...} object list. Internal rotation
    logic keys on filenames; the enriched metadata is rebuilt on write by
    ``_web_index_dump``."""
    p = SNAPSHOTS_WEB / "index.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    return [e if isinstance(e, str) else e["filename"] for e in raw]


# The enriched web-index payload is built + written by the shared
# ``write_public_index`` (pursue_index.scrape.snapshots) so this recovery
# path stays byte-identical to the scrape-run + ingest paths.


def _backfill_missing_pipeline_entries(idx: dict) -> dict:
    """If snapshot files on disk aren't in the pipeline-side index,
    backfill them. This catches the historical drift where the index
    stopped getting updated."""
    indexed_shas = {s["csv_sha256"] for s in idx.get("snapshots", [])}
    for snap in sorted(SNAPSHOTS_PIPELINE.glob("*.json")):
        if snap.name == "index.json":
            continue
        sha = snap.stem
        if sha in indexed_shas:
            continue
        try:
            body = json.loads(snap.read_text())
        except json.JSONDecodeError:
            continue
        idx.setdefault("snapshots", []).append({
            "filename": snap.name,
            "csv_sha256": sha,
            "fetched_at": body.get("fetched_at",
                                   datetime.fromtimestamp(snap.stat().st_mtime,
                                                          tz=UTC).isoformat()),
            "card_count": len(body.get("cards", [])),
        })
    # Sort by fetched_at ascending so the diff page's "newest" lookup
    # is deterministic.
    idx["snapshots"].sort(key=lambda s: s.get("fetched_at", ""))
    return idx


def _backfill_missing_web_entries(idx_list: list[str]) -> list[str]:
    existing_shas = {fn.replace(".json", "") for fn in idx_list}
    for snap in sorted(SNAPSHOTS_WEB.glob("*.json")):
        if snap.name == "index.json":
            continue
        if snap.stem not in existing_shas:
            idx_list.append(snap.name)
    # Sort web index by file mtime ascending; the /diff page picks the
    # last two so newest must be last.
    idx_list.sort(key=lambda fn: (SNAPSHOTS_WEB / fn).stat().st_mtime
                  if (SNAPSHOTS_WEB / fn).exists() else 0)
    return idx_list


def rotate(manifest: dict) -> tuple[bool, str]:
    """Return (rotated_new_snapshot, message)."""
    sha = _current_sha(manifest)
    pipeline_idx = _pipeline_index_load()
    pipeline_idx = _backfill_missing_pipeline_entries(pipeline_idx)
    web_idx = _web_index_load()
    web_idx = _backfill_missing_web_entries(web_idx)

    indexed_pipeline = {s["csv_sha256"] for s in pipeline_idx.get("snapshots", [])}
    indexed_web = {fn.replace(".json", "") for fn in web_idx}

    rotated = False
    msgs = []

    # Pipeline-side: write the snapshot file + add the index entry
    pipeline_snap = SNAPSHOTS_PIPELINE / f"{sha}.json"
    if not pipeline_snap.exists():
        pipeline_snap.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        msgs.append(f"  wrote pipeline snapshot {pipeline_snap.relative_to(_REPO_ROOT)}")
        rotated = True
    if sha not in indexed_pipeline:
        pipeline_idx["snapshots"].append({
            "filename": f"{sha}.json",
            "csv_sha256": sha,
            "fetched_at": manifest.get("fetched_at", datetime.now(UTC).isoformat()),
            "card_count": len(manifest.get("cards", [])),
        })
        msgs.append(f"  added pipeline index entry for {sha[:12]}")
        rotated = True

    # Web-side: copy snapshot file + add index entry
    web_snap = SNAPSHOTS_WEB / f"{sha}.json"
    if not web_snap.exists():
        web_snap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pipeline_snap, web_snap)
        msgs.append(f"  copied web snapshot {web_snap.relative_to(_REPO_ROOT)}")
        rotated = True
    if f"{sha}.json" not in web_idx:
        web_idx.append(f"{sha}.json")
        msgs.append(f"  added web index entry for {sha[:12]}")
        rotated = True

    # Re-sort web index by file mtime (newest last) so the /diff page
    # gets the right "current" pick.
    web_idx.sort(key=lambda fn: (SNAPSHOTS_WEB / fn).stat().st_mtime
                 if (SNAPSHOTS_WEB / fn).exists() else 0)

    # Persist the pipeline index here; the web index goes through the
    # shared writer so its shape + serialization match every other path.
    (SNAPSHOTS_PIPELINE / "index.json").write_text(
        json.dumps(pipeline_idx, indent=2, ensure_ascii=False)
    )
    write_public_index(SNAPSHOTS_WEB)

    if not rotated:
        msgs.append(f"  no-op (sha {sha[:12]} already in both indexes)")
    return rotated, "\n".join(msgs)


def main() -> int:
    manifest = _load_manifest()
    rotated, msg = rotate(manifest)
    print(f"snapshot-rotate: csv_sha={manifest['csv_sha256'][:16]}... "
          f"cards={len(manifest['cards'])}")
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
