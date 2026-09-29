"""Worker retrieval text payload (``web/public/data/retrieve/``).

The Worker must not parse the whole ``pages.json`` on a cold start, so
``scripts/build_retrieve_rows.py`` publishes only what ``/api/retrieve``
reads — ``[card_id, page, title, text]`` per embedding row — sharded in
``embed_index.json`` row order, plus a small per-card title list for the
slug lookup and a manifest naming both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import build_retrieve_rows as brr  # type: ignore[import-not-found] # noqa: E402

from pursue_index.release.chunked_asset import write_asset  # noqa: E402

DATA = REPO_ROOT / "web" / "public" / "data"


def _page(card_id: str, page: int, title: str, text: str) -> dict[str, object]:
    return {
        "id": f"{card_id}-p{page}",
        "card_id": card_id,
        "page": page,
        "title": title,
        "text": text,
        "engine": "x",
        "confidence": "1",
    }


PAGES = [
    _page("bbbb", 1, "DOW-UAP-D017, Report", "b one"),
    _page("aaaa", 2, "CIA-UAP-D001, Memo", "a two"),
    _page("aaaa", 1, "CIA-UAP-D001, Memo", "a one ü"),
    _page("cccc", 1, "No embedding", "c"),
]
INDEX = {"model_id": "voyage-3", "dim": 2, "n": 4, "pages": [
    ["aaaa", 1], ["bbbb", 1], ["gone", 3], ["aaaa", 2],
]}


def _publish_inputs(root: Path) -> None:
    write_asset(root / "pages.json", json.dumps(PAGES).encode())
    write_asset(root / "embed_index.json", json.dumps(INDEX).encode())


def test_rows_follow_index_order_and_carry_only_what_the_worker_reads() -> None:
    rows = brr.build_rows(INDEX, PAGES)
    assert rows == [
        ["aaaa", 1, "CIA-UAP-D001, Memo", "a one ü"],
        ["bbbb", 1, "DOW-UAP-D017, Report", "b one"],
        None,  # an index row with no page record stays a hole, not a blank
        ["aaaa", 2, "CIA-UAP-D001, Memo", "a two"],
    ]


def test_titles_are_one_per_card_in_first_page_order() -> None:
    assert brr.build_titles(PAGES) == [
        ["bbbb", "DOW-UAP-D017, Report"],
        ["aaaa", "CIA-UAP-D001, Memo"],
        ["cccc", "No embedding"],
    ]


def test_shards_split_on_byte_target_and_cover_every_row_once() -> None:
    rows = [["c", i, "t", "x" * 100] for i in range(50)]
    shards = brr.shard_rows(rows, target_bytes=1000)
    assert len(shards) > 1
    assert all(len(body) <= 1000 for _start, body in shards)
    starts = [s for s, _ in shards]
    assert starts[0] == 0
    decoded = [r for _s, body in shards for r in json.loads(body)]
    assert decoded == rows
    for (start, body), nxt in zip(shards, [*starts[1:], len(rows)], strict=True):
        assert start + len(json.loads(body)) == nxt


def test_a_row_over_the_target_gets_a_shard_of_its_own() -> None:
    rows = [["c", 1, "t", "x" * 50], ["c", 2, "t", "y" * 5000], ["c", 3, "t", "z"]]
    shards = brr.shard_rows(rows, target_bytes=1000)
    assert [len(json.loads(b)) for _s, b in shards] == [1, 1, 1]


def test_write_publishes_content_addressed_shards_and_manifest(tmp_path: Path) -> None:
    _publish_inputs(tmp_path)
    manifest = brr.write(tmp_path, target_bytes=64)
    out = tmp_path / "retrieve"
    on_disk = json.loads((out / "rows.json").read_text())
    assert on_disk == manifest
    assert manifest["schema"] == "pursue-retrieve-rows/1"
    assert manifest["n"] == 4
    rows = []
    for shard in manifest["shards"]:
        body = (out / shard["path"]).read_bytes()
        assert len(body) == shard["size"]
        assert brr.content_name("rows", shard["start"], body) == shard["path"]
        part = json.loads(body)
        assert len(part) == shard["count"]
        rows.extend(part)
    assert rows == brr.build_rows(INDEX, PAGES)
    titles = json.loads((out / manifest["titles"]["path"]).read_bytes())
    assert titles == brr.build_titles(PAGES)


def test_rewrite_removes_stale_shards_only(tmp_path: Path) -> None:
    _publish_inputs(tmp_path)
    brr.write(tmp_path, target_bytes=64)
    out = tmp_path / "retrieve"
    (out / "rows-000-0123456789ab.json").write_text("[]")
    (out / "README").write_text("keep")
    manifest = brr.write(tmp_path, target_bytes=64)
    named = {s["path"] for s in manifest["shards"]} | {manifest["titles"]["path"], "rows.json"}
    assert {p.name for p in out.iterdir()} == named | {"README"}


def test_check_reports_a_stale_payload(tmp_path: Path) -> None:
    _publish_inputs(tmp_path)
    assert brr.main(["--data-dir", str(tmp_path), "--check"]) == 1
    assert brr.main(["--data-dir", str(tmp_path)]) == 0
    assert brr.main(["--data-dir", str(tmp_path), "--check"]) == 0
    write_asset(tmp_path / "pages.json", json.dumps(PAGES[:3]).encode())
    assert brr.main(["--data-dir", str(tmp_path), "--check"]) == 1


def test_shards_stay_well_under_two_megabytes() -> None:
    assert brr.TARGET_BYTES <= 1024 * 1024


def test_committed_payload_matches_committed_sources() -> None:
    assert brr.main(["--data-dir", str(DATA), "--check"]) == 0
