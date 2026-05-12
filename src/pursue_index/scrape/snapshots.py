"""Manifest snapshot rotation + upstream-removal detection.

The poll workflow + scrape stage detect when the upstream CSV's SHA
changes. That tells us *something* changed — but not what. Specifically,
when the government quietly removes a previously-released card from the
CSV, the old manifest gets overwritten by the next scrape and we lose
the evidence. This module preserves both sides of the diff so we can
prove what was here before and surface removals to the public.

Three pieces:
  * Snapshot rotation — before writing a new ``latest.json``, copy the
    prior manifest to ``data/manifests/snapshots/<csv_sha>.json`` plus
    a public mirror at ``web/public/data/snapshots/`` for the DiffIsland
    UI to fetch.
  * Index file — ``data/manifests/snapshots/index.json`` enumerates the
    historical snapshots with their csv_sha + fetched_at + card_count
    so the UI doesn't have to read every snapshot to build a list.
  * Removal log — ``data/removed-cards.jsonl`` is append-only;
    each line records a card that disappeared between scrapes, with
    timestamp, prior fetched_at, new csv_sha, and the full prior card
    record so the title/agency/dates are preserved.

Preservation guarantee: this module NEVER deletes from R2 (it doesn't
have a delete path at all) and the OCR pages, embeddings, and cleaned
text for removed cards stay on disk + in the deployed JSON bundles.
Removed cards become a "preserved record" — the bytes are still ours.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# Public + canonical snapshot locations. The public mirror is what the
# DiffIsland fetches at runtime; the canonical copy is what we treat as
# the source of truth (e.g. for offline diffs).
DEFAULT_CANONICAL_DIR = Path("data/manifests/snapshots")
DEFAULT_PUBLIC_DIR = Path("web/public/data/snapshots")
DEFAULT_REMOVED_LOG = Path("data/removed-cards.jsonl")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically: tmp file in same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def rotate_to_snapshot(
    latest_path: Path,
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    public_dir: Path = DEFAULT_PUBLIC_DIR,
) -> Path | None:
    """Copy the current ``latest.json`` to a snapshot file named by its
    ``csv_sha256`` and update the index. No-op if no prior manifest exists
    (first scrape) or if the prior manifest's csv_sha is already snapshotted.

    Returns the canonical snapshot path on success, ``None`` when there
    was nothing to rotate.
    """
    if not latest_path.exists():
        return None
    prior = _read_json(latest_path)
    sha = prior.get("csv_sha256")
    if not sha:
        return None
    canonical_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = canonical_dir / f"{sha}.json"
    public_path = public_dir / f"{sha}.json"
    if snapshot_path.exists():
        # Idempotent — already rotated; ensure public mirror exists too.
        if not public_path.exists():
            public_path.write_bytes(snapshot_path.read_bytes())
        return snapshot_path
    payload = latest_path.read_bytes()
    snapshot_path.write_bytes(payload)
    public_path.write_bytes(payload)
    _rebuild_index(canonical_dir, public_dir)
    return snapshot_path


def _rebuild_index(canonical_dir: Path, public_dir: Path) -> None:
    entries: list[dict[str, Any]] = []
    for path in sorted(canonical_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        m = _read_json(path)
        entries.append(
            {
                "filename": path.name,
                "csv_sha256": m.get("csv_sha256"),
                "fetched_at": m.get("fetched_at"),
                "card_count": len(m.get("cards", [])),
            }
        )
    # Canonical index: full metadata for offline tooling.
    _atomic_write_json(canonical_dir / "index.json", {"snapshots": entries})
    # Public index: filenames only — DiffIsland's contract.
    _atomic_write_json(
        public_dir / "index.json",
        [e["filename"] for e in entries],
    )


def detect_removals(
    prior: dict[str, Any], new: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the prior card records whose ``card_id`` is no longer in
    the new manifest. Empty list when nothing was removed.
    """
    new_ids = {c["card_id"] for c in new.get("cards", [])}
    return [c for c in prior.get("cards", []) if c["card_id"] not in new_ids]


DEFAULT_REMOVED_JSON = Path("web/public/data/removed-cards.json")


def _rebuild_removed_json(
    log_path: Path = DEFAULT_REMOVED_LOG,
    out_path: Path = DEFAULT_REMOVED_JSON,
) -> None:
    """Derive ``web/public/data/removed-cards.json`` from the JSONL log.

    The web RemovedIsland fetches the public JSON at runtime
    (``/data/removed-cards.json``); the canonical write target is the
    JSONL log. Without this rebuild step the JSONL would grow on
    every detected removal but the public surface would silently fall
    behind (vaivora P1). Re-derive on every ``log_removals`` call so
    the two are always in sync.

    The JSON wrapper shape ``{removed: [...]}`` is what the existing
    RemovedIsland.tsx contract reads; sorting newest-first matches
    operator expectation.
    """
    rows: list[dict[str, Any]] = []
    if log_path.exists():
        with log_path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    rows.sort(key=lambda r: r.get("detected_at", ""), reverse=True)
    payload = {"removed": rows}
    _atomic_write_json(out_path, payload)


def log_removals(
    removed: list[dict[str, Any]],
    prior: dict[str, Any],
    new: dict[str, Any],
    log_path: Path = DEFAULT_REMOVED_LOG,
    public_json_path: Path = DEFAULT_REMOVED_JSON,
) -> None:
    """Append one JSONL row per removed card AND rebuild the public JSON.

    Each row carries the full prior card record (title, agency, dates,
    asset_url) plus context (when we noticed, which csv_sha pairs flank
    the transition) so a downstream UI can render a "preserved record"
    surface without needing to cross-reference the snapshot files.

    After appending, derives the public JSON snapshot the RemovedIsland
    consumes so the UI surface tracks the canonical JSONL log
    automatically (vaivora P1 — previously the public JSON was hand-
    authored and would silently drift on the next detected removal).
    """
    if not removed:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    detected_at = datetime.now(UTC).isoformat()
    prior_sha = prior.get("csv_sha256")
    new_sha = new.get("csv_sha256")
    with log_path.open("a", encoding="utf-8") as fh:
        for card in removed:
            entry = {
                "detected_at": detected_at,
                "prior_csv_sha256": prior_sha,
                "new_csv_sha256": new_sha,
                "prior_fetched_at": prior.get("fetched_at"),
                "card": card,
            }
            fh.write(json.dumps(entry) + "\n")
    _rebuild_removed_json(log_path=log_path, out_path=public_json_path)


def rotate_and_diff(
    latest_path: Path,
    new_manifest: dict[str, Any],
    canonical_dir: Path = DEFAULT_CANONICAL_DIR,
    public_dir: Path = DEFAULT_PUBLIC_DIR,
    removed_log: Path = DEFAULT_REMOVED_LOG,
) -> dict[str, Any]:
    """Top-level helper for scrape_run_cmd.

    Snapshots the prior ``latest.json`` (if any), then computes the
    added/removed diff against ``new_manifest`` and logs removals to
    the persistent record. Returns a summary dict the caller can print
    or attach to logs:

        {
            "snapshot": str | None,   # canonical snapshot path, if rotated
            "added": int,             # cards added by the new manifest
            "removed": int,           # cards removed; details in log
            "removed_titles": list[str],  # up to 10 sample titles
        }
    """
    snapshot_path = rotate_to_snapshot(
        latest_path, canonical_dir=canonical_dir, public_dir=public_dir
    )
    if snapshot_path is None:
        return {"snapshot": None, "added": 0, "removed": 0, "removed_titles": []}
    prior = _read_json(snapshot_path)
    removed = detect_removals(prior, new_manifest)
    new_ids = {c["card_id"] for c in new_manifest.get("cards", [])}
    prior_ids = {c["card_id"] for c in prior.get("cards", [])}
    added = len(new_ids - prior_ids)
    if removed:
        log_removals(removed, prior, new_manifest, log_path=removed_log)
    return {
        "snapshot": str(snapshot_path),
        "added": added,
        "removed": len(removed),
        "removed_titles": [c.get("title", "?")[:80] for c in removed[:10]],
    }
