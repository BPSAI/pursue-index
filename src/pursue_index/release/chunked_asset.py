"""Chunked static assets: keep every deployed file under the size budget.

Cloudflare Workers refuses to upload any single static asset over 25 MiB.
A payload under ``web/public/data`` that outgrows :data:`BUDGET_BYTES` is
published as ordered byte-range parts plus a manifest, losslessly::

    embeddings.bin.chunks.json        {"name", "size", "sha256", "parts": [...]}
    embeddings.bin.part-000.bin
    embeddings.bin.part-001.bin

A payload within budget keeps its original URL; its manifest then lists the
whole file as the single part, so readers never have to probe for a 404.
Parts keep the asset's extension so they are served with the same
content type (and compression) as the whole file would have been.

Every reader goes through :func:`read_asset_bytes` here, or the JS twin in
``web/src/lib/chunked-asset.js``; both reassemble the parts and verify the
manifest size. The deploy gate (``scripts/check_asset_budget.py``) uses
:func:`find_budget_violations` and :func:`find_manifest_errors`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# 1 MiB of margin under the 25 MiB Workers static-asset limit.
BUDGET_BYTES = 24 * 1024 * 1024
MANIFEST_SUFFIX = ".chunks.json"
SCHEMA = "pursue-chunked-asset/1"


def manifest_path(path: Path) -> Path:
    """``<dir>/<name>.chunks.json`` for the asset at ``path``."""
    return path.with_name(path.name + MANIFEST_SUFFIX)


PART_DIGEST_HEX = 12


def part_name(name: str, index: int, data: bytes) -> str:
    """``pages.json`` → ``pages.json.part-000-<sha12>.json``.

    Content-addressed: the name carries the first 12 hex digits of the
    part's sha256, so a manifest can only ever name its own release's parts
    — a cached manifest from another release points at files that no longer
    exist (or, if served, fail the per-part sha256). The index keeps the
    order readable; the extension keeps the content type.
    """
    digest = hashlib.sha256(data).hexdigest()[:PART_DIGEST_HEX]
    return f"{name}.part-{index:03d}-{digest}{Path(name).suffix}"


def _part_name_ok(name: str, index: int, part: str) -> bool:
    pattern = (
        re.escape(f"{name}.part-{index:03d}-")
        + f"[0-9a-f]{{{PART_DIGEST_HEX}}}"
        + re.escape(Path(name).suffix)
    )
    return re.fullmatch(pattern, part) is not None


def _existing_parts(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.part-*"))


def _split(data: bytes, budget: int) -> list[bytes]:
    """Near-equal parts, each <= ``budget`` bytes."""
    count = max(1, math.ceil(len(data) / budget))
    step = math.ceil(len(data) / count) if data else 0
    return [data[i * step:(i + 1) * step] for i in range(count)]


def write_asset(path: Path, data: bytes, *, budget: int = BUDGET_BYTES) -> list[Path]:
    """Publish ``data`` at ``path``: whole if within budget, else as parts.

    Always (re)writes the manifest and removes files left over from the
    other shape, so a tree never carries both a whole file and parts.
    Returns the written data files (whole file or parts).
    """
    if budget <= 0:
        raise ValueError(f"budget must be positive, got {budget}")
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks = [data] if len(data) <= budget else _split(data, budget)
    if len(chunks) == 1:
        targets = [path]
    else:
        targets = [path.with_name(part_name(path.name, i, c)) for i, c in enumerate(chunks)]
    stale = set(_existing_parts(path)) | {path}
    for target, chunk in zip(targets, chunks, strict=True):
        target.write_bytes(chunk)
        stale.discard(target)
    manifest = {
        "schema": SCHEMA,
        "name": path.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "parts": [
            {"path": t.name, "size": len(c), "sha256": hashlib.sha256(c).hexdigest()}
            for t, c in zip(targets, chunks, strict=True)
        ],
    }
    manifest_path(path).write_text(json.dumps(manifest, indent=2) + "\n")
    # Previous releases' parts go only once the new manifest is in place.
    for leftover in stale:
        leftover.unlink(missing_ok=True)
    return targets


def _load_manifest(mpath: Path) -> dict[str, Any]:
    manifest = json.loads(mpath.read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("parts"), list):
        raise ValueError(f"{mpath.name}: not a chunk manifest")
    for part in manifest["parts"]:
        name = part.get("path") if isinstance(part, dict) else None
        if not isinstance(name, str) or Path(name).name != name or name.startswith("."):
            raise ValueError(f"{mpath.name}: bad part path {name!r}")
    parts = manifest["parts"]
    if len(parts) > 1:
        for i, part in enumerate(parts):
            if not _part_name_ok(str(manifest.get("name")), i, part["path"]):
                raise ValueError(
                    f"{mpath.name}: part name {part['path']!r} is not the content-addressed "
                    f"name for part {i} of {manifest.get('name')!r}"
                )
    elif parts and parts[0]["path"] != manifest.get("name"):
        raise ValueError(f"{mpath.name}: single part name {parts[0]['path']!r} is not the asset")
    return manifest


def _assemble(mpath: Path, manifest: dict[str, Any]) -> bytes:
    buf = bytearray()
    for part in manifest["parts"]:
        ppath = mpath.parent / part["path"]
        data = ppath.read_bytes()
        if len(data) != part["size"]:
            raise ValueError(
                f"{manifest['name']}: part {part['path']} is {len(data)} bytes, "
                f"manifest says {part['size']}"
            )
        if "sha256" in part and hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise ValueError(
                f"{manifest['name']}: part {part['path']} sha256 does not match the manifest"
            )
        buf += data
    whole = bytes(buf)
    if len(whole) != manifest["size"] or hashlib.sha256(whole).hexdigest() != manifest["sha256"]:
        raise ValueError(f"{manifest['name']}: reassembled bytes do not match the manifest")
    return whole


def read_asset_bytes(path: Path) -> bytes:
    """Bytes of the asset at ``path``, reassembled from parts if chunked.

    Falls back to the plain file when no manifest exists. Raises
    :class:`FileNotFoundError` when neither is present and
    :class:`ValueError` when parts disagree with the manifest.
    """
    mpath = manifest_path(path)
    if mpath.is_file():
        return _assemble(mpath, _load_manifest(mpath))
    return path.read_bytes()


def read_asset_text(path: Path) -> str:
    return read_asset_bytes(path).decode("utf-8")


def read_asset_json(path: Path) -> Any:
    return json.loads(read_asset_bytes(path))


def asset_exists(path: Path) -> bool:
    return manifest_path(path).is_file() or path.is_file()


def find_budget_violations(roots: Iterable[Path], *, budget: int = BUDGET_BYTES) -> list[tuple[Path, int]]:
    """Every file under ``roots`` larger than ``budget``, as ``(path, size)``."""
    out: list[tuple[Path, int]] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for p in files:
            size = p.stat().st_size
            if size > budget:
                out.append((p, size))
    return out


def _manifest_problems(mpath: Path) -> list[str]:
    try:
        manifest = _load_manifest(mpath)
        name = manifest["name"]
        if mpath.name != name + MANIFEST_SUFFIX:
            return [f"{mpath}: names asset {name!r}, expected {mpath.name[:-len(MANIFEST_SUFFIX)]!r}"]
        _assemble(mpath, manifest)
    except FileNotFoundError as exc:
        return [f"{mpath}: missing part {Path(str(exc.filename)).name}"]
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{mpath}: {exc}"]
    problems = []
    whole = mpath.parent / name
    if len(manifest["parts"]) > 1 and whole.exists():
        problems.append(f"{mpath}: stale whole file {name} ships alongside its parts")
    listed = {p["path"] for p in manifest["parts"]}
    for extra in _existing_parts(whole):
        if extra.name not in listed:
            problems.append(f"{mpath}: unlisted part {extra.name}")
    return problems


def find_manifest_errors(roots: Iterable[Path]) -> list[str]:
    """Manifests whose parts are missing, drifted, or shadowed by a whole file."""
    errors: list[str] = []
    for root in roots:
        if root.is_dir():
            for mpath in sorted(root.rglob(f"*{MANIFEST_SUFFIX}")):
                errors.extend(_manifest_problems(mpath))
    return errors
