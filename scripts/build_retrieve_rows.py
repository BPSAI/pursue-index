#!/usr/bin/env python3
"""Build the Worker's retrieval text payload: ``web/public/data/retrieve/``.

``/api/retrieve`` needs the title and text of at most ~20 pages per query,
but parsing the whole ``pages.json`` for them (bytes, then a UTF-16 string,
then an object graph) is most of a cold Workers isolate's 128 MB. This
payload holds only what the Worker reads, in ``embed_index.json`` row order,
so it can fetch just the shards holding a query's hits:

  retrieve/rows.json                 manifest (always revalidated)
  retrieve/rows-<start>-<sha12>.json [[card_id, page, title, text] | null, ...]
  retrieve/titles-0-<sha12>.json     [[card_id, title], ...] for the slug lookup

Row ``i`` of the shards is embedding row ``i``; an index row without a page
record is ``null`` (the Worker skips it, logged). Shards are cut at
``TARGET_BYTES`` so each stays well under 2 MB; names are content-addressed
so a manifest never pairs with another release's shards.

Derived from the committed ``pages.json`` and ``embed_index.json`` only, so
it runs without the data root (``make rebuild-derivatives`` runs it after
the embed index). ``--check`` exits 1 when the committed payload is stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.release.chunked_asset import read_asset_json  # noqa: E402

DEFAULT_DATA_DIR = REPO_ROOT / "web" / "public" / "data"
OUT_DIRNAME = "retrieve"
MANIFEST_NAME = "rows.json"
SCHEMA = "pursue-retrieve-rows/1"
TARGET_BYTES = 1024 * 1024
_CONTENT_NAME = re.compile(r"(rows|titles)-\d+-[0-9a-f]{12}\.json")

Row = list[Any]


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def content_name(kind: str, start: int, body: bytes) -> str:
    return f"{kind}-{start}-{hashlib.sha256(body).hexdigest()[:12]}.json"


def build_rows(index: dict[str, Any], pages: list[dict[str, Any]]) -> list[Row | None]:
    """``[card_id, page, title, text]`` per index row; ``None`` for a hole."""
    by_key = {(str(p["card_id"]), int(p["page"])): p for p in pages}
    rows: list[Row | None] = []
    for card_id, page in index["pages"]:
        rec = by_key.get((str(card_id), int(page)))
        rows.append(None if rec is None else [card_id, page, rec.get("title") or "", rec.get("text") or ""])
    return rows


def build_titles(pages: list[dict[str, Any]]) -> list[list[str]]:
    """One ``[card_id, title]`` per card, in first-page order.

    The Worker's slug index takes the first card whose title carries a slug,
    so the order is the order the full ``pages.json`` scan would meet them.
    """
    seen: dict[str, str] = {}
    for p in pages:
        seen.setdefault(str(p["card_id"]), str(p.get("title") or ""))
    return [[card_id, title] for card_id, title in seen.items()]


def shard_rows(rows: list[Row | None], target_bytes: int = TARGET_BYTES) -> list[tuple[int, bytes]]:
    """``(first_row, json_bytes)`` shards in row order, each <= target bytes
    unless a single row is larger on its own."""
    shards: list[tuple[int, bytes]] = []
    start = 0
    encoded: list[bytes] = []
    size = 2  # the enclosing brackets
    for i, row in enumerate(rows):
        body = _dumps(row)
        extra = len(body) + (1 if encoded else 0)
        if encoded and size + extra > target_bytes:
            shards.append((start, b"[" + b",".join(encoded) + b"]"))
            start, encoded, size = i, [], 2
            extra = len(body)
        encoded.append(body)
        size += extra
    if encoded:
        shards.append((start, b"[" + b",".join(encoded) + b"]"))
    return shards


def render(data_dir: Path, target_bytes: int = TARGET_BYTES) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The manifest and every file it names, from the committed sources."""
    index = read_asset_json(data_dir / "embed_index.json")
    pages = read_asset_json(data_dir / "pages.json")
    rows = build_rows(index, pages)
    files: dict[str, bytes] = {}
    shards = []
    for start, body in shard_rows(rows, target_bytes):
        name = content_name("rows", start, body)
        files[name] = body
        count = len(json.loads(body))
        shards.append({"start": start, "count": count, "path": name, "size": len(body)})
    titles_body = _dumps(build_titles(pages))
    titles_name = content_name("titles", 0, titles_body)
    files[titles_name] = titles_body
    manifest = {
        "schema": SCHEMA,
        "n": len(rows),
        "shards": shards,
        "titles": {"path": titles_name, "size": len(titles_body)},
    }
    return manifest, files


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, indent=1) + "\n").encode("utf-8")


def write(data_dir: Path, target_bytes: int = TARGET_BYTES) -> dict[str, Any]:
    manifest, files = render(data_dir, target_bytes)
    out = data_dir / OUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        path = out / name
        if not path.exists() or path.read_bytes() != body:
            path.write_bytes(body)
    (out / MANIFEST_NAME).write_bytes(_manifest_bytes(manifest))
    # Previous builds' shards go only once the new manifest is in place.
    for path in out.iterdir():
        if _CONTENT_NAME.fullmatch(path.name) and path.name not in files:
            path.unlink()
    return manifest


def stale(data_dir: Path, target_bytes: int = TARGET_BYTES) -> list[str]:
    """Why the published payload differs from a fresh build (empty if not)."""
    manifest, files = render(data_dir, target_bytes)
    out = data_dir / OUT_DIRNAME
    mpath = out / MANIFEST_NAME
    if not mpath.exists() or mpath.read_bytes() != _manifest_bytes(manifest):
        return [f"{mpath} is missing or out of date"]
    return [
        f"{out / name} is missing or differs"
        for name, body in files.items()
        if not (out / name).exists() or (out / name).read_bytes() != body
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--check", action="store_true", help="exit 1 if the payload is stale")
    args = parser.parse_args(argv)
    if args.check:
        problems = stale(args.data_dir)
        for line in problems:
            print(f"retrieve rows: {line}; run scripts/build_retrieve_rows.py", file=sys.stderr)
        return 1 if problems else 0
    manifest = write(args.data_dir)
    total = sum(s["size"] for s in manifest["shards"])
    print(
        f"wrote {args.data_dir / OUT_DIRNAME} ({total / 2**20:.1f} MB): "
        f"{manifest['n']} rows in {len(manifest['shards'])} shards"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
