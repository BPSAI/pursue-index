"""Tranche-diff analyzer for upstream re-cataloging events.

Reads the previously-promoted manifest (`data/manifests/latest.json`)
and the freshly-scraped candidate manifest snapshot
(`data/manifests/snapshots/<new_csv_sha>.json`), classifies every
new card_id into one of three classes, and emits a structured report
for operator approval before `pursue ingest run` promotes the new
tranche into the deployed corpus state.

The three classes:

  * Class A — confirmed rename. New `(asset_url, title)` produces a
    new card_id, but the fetched bytes hash to a byte_sha256 already
    present in `data/asset-bytes-registry.jsonl`. Operator-approval
    queues a row in `data/card-aliases.json` so the worker resolver
    redirects `/card/<old_id>` → `/card/<new_id>`. Both card identities
    preserved.

  * Class B — net-new content. New card_id, new byte_sha256, no
    title-continuity heuristic match against any prior card. Ingest
    normally as a first-time card.

  * Class C — suspicious replacement. New card_id, new byte_sha256,
    but at least one title-continuity heuristic matches a prior card.
    Quarantined for manual operator review — could be a legitimate
    re-redaction the upstream owns OR could be tampering disguised as
    a rename.

Also reports:
  * Removed cards (in old manifest, no byte-sha match in new) →
    candidates for `/removed` editorial-public surface
  * Field-only changes (same card_id, different metadata fields)

Outputs:
  * `data/tranche-diffs/tranche-diff-<csv_sha>.json` — machine-readable
  * `data/tranche-diffs/tranche-diff-<csv_sha>.md`   — operator-readable

Both files are committed alongside the new CSV sha so the report
becomes a permanent receipt of how each tranche was classified at
detection time. `pursue ingest approve` reads the JSON back from the
same directory and refuses approval if any byte-sha has moved since,
so the output location must stay tracked and must match
`ingest_cli.DEFAULT_DIFF_DIR`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pursue_index.tranche import (  # noqa: E402
    build_byte_sha_index,
    find_title_continuity,
)
from pursue_index.tranche_manifest import (  # noqa: E402
    build_field_only_changes,
    build_removed_list,
    build_row_changes,
    display_rows_by_card_id,
    group_by_card_id,
)
from pursue_index.tranche_report import render_json, render_markdown  # noqa: E402
from r2_archive_assets import load_registry  # noqa: E402

DEFAULT_OLD_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
# Receipts are a permanent record, so they must live in a TRACKED directory.
# `.paircoder/` is gitignored — writing here would drop them silently.
DEFAULT_OUT_DIR = _REPO_ROOT / "data" / "tranche-diffs"


def _fetch_byte_sha_via_curl(url: str) -> str | None:
    """Default network fetcher — GET via curl_cffi Chrome impersonation,
    hash the bytes. Returns None on any error so the caller can fall
    back to "no byte_sha observed for this URL" classification.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None
    try:
        resp = cffi_requests.get(url, impersonate="chrome", timeout=300)
        resp.raise_for_status()
        return hashlib.sha256(resp.content).hexdigest()
    except Exception as exc:
        print(f"[tranche-diff] fetch fail {url}: {exc}", file=sys.stderr)
        return None


def _classify_restoration(
    cid: str,
    new_card: dict[str, Any],
    sha: str | None,
    prior_rows: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Restoration sub-classifier: card_id is already in the registry,
    which means we've archived bytes under this card_id before. Decide
    whether the reappearance is byte-identical (safe) or modified
    (suspicious).
    """
    pinned_sha = prior_rows[-1].get("byte_sha256")
    base = {
        "new_card_id": cid,
        "new_title": new_card.get("title"),
        "new_asset_filename": new_card.get("asset_filename"),
        "new_asset_url": new_card.get("asset_url"),
        "pinned_byte_sha256": pinned_sha,
        "pinned_fetched_at": prior_rows[-1].get("fetched_at"),
    }
    if sha is None:
        return ("RESTORED_UNKNOWN", {**base, "new_byte_sha256": None})
    base["new_byte_sha256"] = sha
    if sha == pinned_sha:
        return ("RESTORED_UNCHANGED", base)
    return ("RESTORED_MODIFIED", base)


def _classify_added_card(
    cid: str,
    new_card: dict[str, Any],
    sha: str | None,
    sha_to_old_card_ids: dict[str, list[str]],
    removed_old_cards: list[dict[str, Any]],
    registry: dict[str, list[dict[str, Any]]],
) -> tuple[str, dict[str, Any]]:
    """Decide the class for one added card. Returns (label, row_dict)
    where label is one of:
      RESTORED_UNCHANGED, RESTORED_MODIFIED, RESTORED_UNKNOWN, A, B, C.

    Restoration takes precedence over A/B/C — if we've previously
    archived this exact card_id under any circumstance (including a
    /removed pin), the reappearance is a restoration event regardless
    of byte-sha collisions with other card_ids.
    """
    prior_rows = registry.get(cid, [])
    if prior_rows:
        return _classify_restoration(cid, new_card, sha, prior_rows)
    if sha and sha in sha_to_old_card_ids:
        old_id = sha_to_old_card_ids[sha][0]
        return ("A", {
            "old_card_id": old_id,
            "new_card_id": cid,
            "byte_sha256": sha,
            "new_title": new_card.get("title"),
            "new_asset_filename": new_card.get("asset_filename"),
            "new_asset_url": new_card.get("asset_url"),
        })
    matches = find_title_continuity(new_card, removed_old_cards)
    if matches:
        # Preserve per-match data so the report can show signal strength
        # per candidate rather than unioning reasons across all candidates
        # (which loses the operator's ability to distinguish "strong
        # match on numeric_id + agency" from "weak match on shared
        # location alone"). Rank by reason count descending — more
        # heuristics firing = stronger candidate.
        ranked = sorted(matches, key=lambda m: -len(m["reasons"]))
        return ("C", {
            "new_card_id": cid,
            "new_title": new_card.get("title"),
            "new_asset_filename": new_card.get("asset_filename"),
            "new_asset_url": new_card.get("asset_url"),
            "new_byte_sha256": sha,
            "matched_against": [m["card_id"] for m in ranked],
            "matches": [
                {
                    "card_id": m["card_id"],
                    "title": (m["card"].get("title") or "")[:80],
                    "reasons": m["reasons"],
                    "strength": len(m["reasons"]),
                }
                for m in ranked
            ],
        })
    return ("B", {
        "new_card_id": cid,
        "title": new_card.get("title"),
        "asset_filename": new_card.get("asset_filename"),
        "asset_url": new_card.get("asset_url"),
        "byte_sha256": sha,
    })


def _classify_added_cards(
    added_ids: set[str],
    new_by_id: dict[str, dict[str, Any]],
    sha_to_old_card_ids: dict[str, list[str]],
    removed_old_cards: list[dict[str, Any]],
    registry: dict[str, list[dict[str, Any]]],
    fetch_byte_sha: Callable[[str], str | None],
) -> dict[str, Any]:
    """Run classification across every added card_id. Returns a dict
    holding all classification buckets plus matched_old_ids (used by
    the caller to suppress entries from the removed list).
    """
    buckets: dict[str, list] = {
        "renames_confirmed": [],
        "new_content": [],
        "quarantined": [],
        "restored_unchanged": [],
        "restored_modified": [],
        "restored_unknown": [],
    }
    matched_old_ids: set[str] = set()
    label_to_bucket = {
        "A": "renames_confirmed",
        "B": "new_content",
        "C": "quarantined",
        "RESTORED_UNCHANGED": "restored_unchanged",
        "RESTORED_MODIFIED": "restored_modified",
        "RESTORED_UNKNOWN": "restored_unknown",
    }
    for cid in sorted(added_ids):
        new_card = new_by_id[cid]
        url = new_card.get("asset_url")
        sha = fetch_byte_sha(url) if url else None
        klass, row = _classify_added_card(
            cid, new_card, sha, sha_to_old_card_ids, removed_old_cards, registry
        )
        buckets[label_to_bucket[klass]].append(row)
        if klass == "A":
            matched_old_ids.add(row["old_card_id"])
    buckets["matched_old_ids"] = matched_old_ids
    return buckets


def diff_tranches(
    old_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    registry: dict[str, list[dict[str, Any]]],
    fetch_byte_sha: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Compute the structured diff between two manifests.

    `registry` is the `{card_id: [rows]}` shape produced by
    `r2_archive_assets.load_registry`. `fetch_byte_sha` is injected
    so tests can provide a synthetic byte-sha map without network.
    """
    if fetch_byte_sha is None:
        fetch_byte_sha = _fetch_byte_sha_via_curl
    old_groups = group_by_card_id(old_manifest.get("cards", []))
    new_groups = group_by_card_id(new_manifest.get("cards", []))
    # A card_id can be backed by several rows; the PDF row is the one
    # that describes the card in add/remove reports and the one whose
    # asset_url is hashed. Keying a dict by card_id would keep whichever
    # row came last, describing a document by one of its videos.
    old_by_id = display_rows_by_card_id(old_manifest.get("cards", []))
    new_by_id = display_rows_by_card_id(new_manifest.get("cards", []))
    removed_ids = set(old_by_id) - set(new_by_id)
    added_ids = set(new_by_id) - set(old_by_id)
    unchanged_ids = set(old_by_id) & set(new_by_id)

    sha_to_old_card_ids = build_byte_sha_index(registry)
    removed_old_cards = [old_by_id[oid] for oid in removed_ids]
    buckets = _classify_added_cards(
        added_ids, new_by_id, sha_to_old_card_ids, removed_old_cards,
        registry, fetch_byte_sha,
    )
    matched_old_ids = buckets.pop("matched_old_ids")
    removed = build_removed_list(removed_ids, matched_old_ids, old_by_id)
    field_only_changes = build_field_only_changes(unchanged_ids, old_groups, new_groups)
    row_change_list = build_row_changes(unchanged_ids, old_groups, new_groups)

    return {
        "tranche_sha256": new_manifest.get("csv_sha256"),
        "prior_manifest_sha": old_manifest.get("csv_sha256"),
        "summary": {
            "renames_confirmed": len(buckets["renames_confirmed"]),
            "new_content": len(buckets["new_content"]),
            "quarantined": len(buckets["quarantined"]),
            "restored_unchanged": len(buckets["restored_unchanged"]),
            "restored_modified": len(buckets["restored_modified"]),
            "restored_unknown": len(buckets["restored_unknown"]),
            "removed": len(removed),
            "field_only_changes": len(field_only_changes),
            "row_changes": len(row_change_list),
        },
        **buckets,
        "removed": removed,
        "field_only_changes": field_only_changes,
        "row_changes": row_change_list,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"cards": [], "csv_sha256": None}
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-manifest", type=Path, default=DEFAULT_OLD_MANIFEST)
    parser.add_argument("--new-manifest", type=Path, required=True,
                        help="Path to the new candidate manifest snapshot")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout instead of writing files")
    args = parser.parse_args()

    old_manifest = _load_manifest(args.old_manifest)
    new_manifest = _load_manifest(args.new_manifest)
    registry = load_registry(args.registry)
    diff = diff_tranches(old_manifest, new_manifest, registry)

    sha = (diff.get("tranche_sha256") or "unknown")[:12]
    if args.dry_run:
        print(render_markdown(diff))
        return 0
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"tranche-diff-{sha}.json"
    md_path = args.out_dir / f"tranche-diff-{sha}.md"
    json_path.write_text(render_json(diff) + "\n")
    md_path.write_text(render_markdown(diff))
    print(f"[tranche-diff] wrote {json_path} and {md_path}")
    print(f"[tranche-diff] summary: {diff['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
