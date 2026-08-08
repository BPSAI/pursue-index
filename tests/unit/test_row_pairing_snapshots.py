"""Row pairing exercised against the REAL snapshots on disk.

`data/manifests/snapshots/` holds every upstream manifest we have
fetched. The receipt generator must describe a transition between two of
them exactly as the /diff page does, so these tests pin the behaviour
against actual upstream data rather than hand-written literals. The
TypeScript twin is `web/src/components/row-pairing.test.ts`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (_SRC, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tranche_diff  # noqa: E402

from pursue_index.tranche import field_diff, row_changes  # noqa: E402
from pursue_index.tranche_rows import pair_rows_by_card_id  # noqa: E402

_SNAPSHOT_DIR = _REPO_ROOT / "data" / "manifests" / "snapshots"


def _snapshot_paths() -> list[Path]:
    return sorted(p for p in _SNAPSHOT_DIR.glob("*.json") if p.name != "index.json")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_prefix(prefix: str) -> dict[str, Any]:
    matches = [p for p in _snapshot_paths() if p.name.startswith(prefix)]
    assert matches, f"no snapshot on disk starting with {prefix}"
    return _load(matches[0])


def _field_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    result = tranche_diff.diff_tranches(
        old_manifest=old, new_manifest=new, registry={},
        fetch_byte_sha=lambda url: None,
    )
    return result["field_only_changes"]


@pytest.mark.parametrize("path", _snapshot_paths(), ids=lambda p: p.name[:8])
def test_snapshot_diffed_against_itself_reports_nothing(path: Path) -> None:
    manifest = _load(path)
    cards = manifest["cards"]
    pairs, unpaired = pair_rows_by_card_id(cards, cards)
    assert len(pairs) == len(cards)
    assert unpaired == []
    assert _field_changes(manifest, manifest) == []


def test_13e730c1_to_5f5698f1_reports_ten_featured_changes() -> None:
    changes = _field_changes(_load_prefix("13e730c1"), _load_prefix("5f5698f1"))
    assert len(changes) == 10
    assert {d["field"] for c in changes for d in c["diffs"]} == {"featured"}


def test_c9cc83fc_to_f75e2f7d_reports_the_asset_type_change() -> None:
    # asset_type is a reported field, so it must not gate pairing: keying
    # on it means a row whose asset_type moves never pairs and the change
    # is never reported at all.
    old, new = _load_prefix("c9cc83fc"), _load_prefix("f75e2f7d")
    target = "167f6a21c7238d0c"
    changes = _field_changes(old, new)
    hit = [c for c in changes if c["card_id"] == target]
    assert hit, "asset_type change on 167f6a21c7238d0c was not reported"
    assert {"field": "asset_type", "old": "VID", "new": "AUD"} in hit[0]["diffs"]


def test_single_row_card_whose_asset_url_changes_is_reported() -> None:
    manifest = _load_prefix("f75e2f7d")
    cards = manifest["cards"]
    counts: dict[str, int] = {}
    for c in cards:
        counts[c["card_id"]] = counts.get(c["card_id"], 0) + 1
    single = next(c for c in cards if counts[c["card_id"]] == 1 and c.get("asset_url"))
    mutated = [
        {**c, "asset_url": f"{c['asset_url']}?rev=2"} if c is single else c
        for c in cards
    ]
    changes = _field_changes(manifest, {**manifest, "cards": mutated})
    assert len(changes) == 1
    assert changes[0]["card_id"] == single["card_id"]
    assert [d["field"] for d in changes[0]["diffs"]] == ["asset_url"]


def test_reordering_identical_vid_rows_reports_nothing() -> None:
    manifest = _load_prefix("5f5698f1")
    cards = manifest["cards"]
    target = "ea029a05470b8f4e"
    vids = [c for c in cards if c["card_id"] == target and c["asset_type"] == "VID"]
    assert len(vids) == 3
    reversed_vids = list(reversed(vids))
    it = iter(reversed_vids)
    reordered = [
        next(it) if (c["card_id"] == target and c["asset_type"] == "VID") else c
        for c in cards
    ]
    assert _field_changes(manifest, {**manifest, "cards": reordered}) == []


def test_added_and_withdrawn_rows_reach_the_receipt() -> None:
    manifest = _load_prefix("5f5698f1")
    target = "ea029a05470b8f4e"
    group = [c for c in manifest["cards"] if c["card_id"] == target]
    extra = {**group[1], "dvids_video_id": "9999999", "title": "DOW-UAP-PR034"}

    added = row_changes(group, [*group, extra])
    assert added == [{
        "side": "added", "asset_type": "VID", "title": "DOW-UAP-PR034",
        "asset_url": extra["asset_url"], "dvids_video_id": "9999999",
    }]

    withdrawn = row_changes([*group, extra], group)
    assert [r["side"] for r in withdrawn] == ["removed"]
    assert withdrawn[0]["dvids_video_id"] == "9999999"
    # A row that only moved position is not a change.
    assert row_changes(group, list(reversed(group))) == []
    assert field_diff(group, list(reversed(group))) == []
