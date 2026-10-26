"""Inputs for replaying the committed Release-7 tranche diff 096ef2c0058a.

Replays use the receipt's own inputs: the old manifest is the receipt's
``prior_manifest_sha`` snapshot (c3f8...) -- ``data/manifests/latest.json``
has since been promoted TO 096ef, so it is no longer the prior manifest --
and the registry is today's registry minus the rows appended when the
tranche's 29 added cards were archived, which is exactly the registry the
receipt was computed against (the release commit only appended those rows).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"
RECEIPT = DATA / "tranche-diffs" / "tranche-diff-096ef2c0058a"
_SNAPSHOTS = DATA / "manifests" / "snapshots"
NEW_MANIFEST = _SNAPSHOTS / "096ef2c0058abd412a568d630df31cb836241c1c08c4f67bdc8cdb7e5c8418b9.json"
OLD_MANIFEST = _SNAPSHOTS / "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7.json"
D042_OLD_ID, D042_NEW_ID = "a0f6663169c21caf", "ff3939f95d878062"
_ROW_KEYS = ("renames_confirmed", "new_content", "quarantined",
             "restored_unchanged", "restored_modified", "restored_unknown")


def receipt() -> dict:
    return json.loads(RECEIPT.with_suffix(".json").read_text())


def receipt_shas() -> dict[str, str]:
    """``asset_url -> byte sha`` exactly as the receipt recorded them."""
    out = {}
    for key in _ROW_KEYS:
        for row in receipt()[key]:
            url = row.get("new_asset_url") or row.get("asset_url")
            if url:
                out[url] = row.get("new_byte_sha256") or row.get("byte_sha256")
    return out


def d042_new_url() -> str:
    [row] = [q for q in receipt()["quarantined"] if q["new_card_id"] == D042_NEW_ID]
    return row["new_asset_url"]


def receipt_time_registry(out: Path, extra_rows: list[dict] | None = None) -> Path:
    """Write the receipt-time registry (plus ``extra_rows``) to ``out``."""
    def ids(path: Path) -> set[str]:
        return {c["card_id"] for c in json.loads(path.read_text())["cards"]}

    added = ids(NEW_MANIFEST) - ids(OLD_MANIFEST)
    lines = (DATA / "asset-bytes-registry.jsonl").read_text().splitlines()
    kept = [ln for ln in lines if ln.strip() and json.loads(ln)["card_id"] not in added]
    out.write_text("\n".join(kept + [json.dumps(r) for r in extra_rows or []]) + "\n")
    return out
