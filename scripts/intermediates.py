#!/usr/bin/env python3
"""Pack the pipeline's intermediates, and prove the published payloads rebuild from them.

The published search, cleaned-text and embedding payloads derive from three
intermediates that a clone does not have: the per-page OCR and transcript text,
the cleaning sidecars, and the float32 embedding vectors. Regenerating them
costs money and does not reproduce them (LLM OCR and cleanup are
nondeterministic), so they are published as a versioned release asset instead:

    python scripts/intermediates.py pack --data-root <data root> --out-dir <dir> --label v1.7.0
    python scripts/intermediates.py rebuild-check --tarball <dir>/intermediates-v1.7.0.tar.gz

``pack`` writes ``intermediates-<label>.tar.gz`` (deterministic: sorted
members, zeroed times and owners, so the same inputs give the same bytes) with
a ``MANIFEST.json`` of every file's sha256, plus ``SHA256SUMS`` beside it.

``rebuild-check`` unpacks a tarball into a scratch directory, checks every file
against its manifest, runs this checkout's builders on it alone (no data root,
no network, no paid calls), and compares their output with the committed
payloads: ``pages.json``, ``pages-cleaned.json``, ``embed_index.json`` and
``embeddings.bin``. The build timestamps in ``pages-cleaned.json``'s ``meta``
are ignored; any other difference fails (exit 1) and is reported by field.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any

from pursue_index.paths import repo_root
from pursue_index.release.chunked_asset import read_asset_bytes, read_asset_json

# The builders run from beside this script (each bootstraps its own src/).
SCRIPTS_DIR = Path(__file__).resolve().parent


def published_dir() -> Path:
    """The committed payloads the rebuild is compared with."""
    return repo_root() / "web" / "public" / "data"

MANIFEST_NAME = "MANIFEST.json"
SCHEMA = "pursue-intermediates/v1"
# Per card, what the builders read from the OCR directory.
CARD_FILES = ("meta.json", "pages.jsonl", "pages_cleaned.jsonl", "pages_cleaned_qc.jsonl")
EMBED_MODEL = "voyage-3"
EMBED_FILES = ("index.json", "vectors.bin")
# Payload name -> builder output name, compared as logical (unchunked) bytes.
PAYLOADS = ("pages.json", "pages-cleaned.json", "embed_index.json", "embeddings.bin")
# Unpack limits for an untrusted tarball, checked from the headers before any
# byte is written. The real asset is ~1,240 files and ~180 MB unpacked.
MAX_MEMBERS = 20_000
MAX_MEMBER_BYTES = 1 << 30  # 1 GiB
MAX_TOTAL_BYTES = 4 << 30  # 4 GiB


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect(data_root: Path) -> list[tuple[str, Path]]:
    """``(archive path, source path)`` for every intermediate, sorted."""
    out: list[tuple[str, Path]] = []
    ocr = data_root / "ocr"
    emb = data_root / "embeddings" / EMBED_MODEL
    # The parent directories must be real directories too: a symlinked
    # ocr/ or embeddings/ would pull files from outside the data root.
    for parent in (ocr, data_root / "embeddings", emb):
        if parent.is_symlink() or not parent.is_dir():
            raise SystemExit(f"intermediates: {parent} must be a real directory")
    # Never follow a symlinked card directory out of the data root.
    for card_dir in sorted(p for p in ocr.iterdir() if p.is_dir() and not p.is_symlink()):
        for name in CARD_FILES:
            src = card_dir / name
            if src.is_file() and not src.is_symlink():
                out.append((f"ocr/{card_dir.name}/{name}", src))
    for name in EMBED_FILES:
        src = emb / name
        if not src.is_file() or src.is_symlink():
            raise SystemExit(f"intermediates: missing {src}")
        out.append((f"embeddings/{EMBED_MODEL}/{name}", src))
    return sorted(out)


def _tarinfo(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = size, 0, 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def pack(data_root: Path, out_dir: Path, label: str) -> Path:
    if not label or "/" in label or label.startswith("."):
        raise SystemExit(f"intermediates: bad --label {label!r}")
    files = collect(data_root)
    blobs = {arc: src.read_bytes() for arc, src in files}
    manifest = {
        "schema": SCHEMA,
        "label": label,
        "files": {arc: {"sha256": sha256_bytes(b), "bytes": len(b)} for arc, b in blobs.items()},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = out_dir / f"intermediates-{label}.tar.gz"
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        body = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
        tar.addfile(_tarinfo(MANIFEST_NAME, len(body)), io.BytesIO(body))
        for arc, data in blobs.items():
            tar.addfile(_tarinfo(arc, len(data)), io.BytesIO(data))
    with tar_path.open("wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0,
                                                  compresslevel=9, filename="") as gz:
        gz.write(raw.getvalue())
    digest = _sha256_file(tar_path)
    (out_dir / "SHA256SUMS").write_text(f"{digest}  {tar_path.name}\n", encoding="utf-8")
    print(f"intermediates: {len(blobs)} files -> {tar_path} "
          f"({tar_path.stat().st_size / 1e6:.1f} MB), sha256 {digest}")
    return tar_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_sums(tarball: Path, expect: str | None = None) -> str:
    """The tarball's sha256, which must match SHA256SUMS beside it.

    SHA256SUMS comes with the tarball, so it catches corruption, not
    tampering. ``expect`` pins the sha256 from an independent source (the
    release notes, or a value recorded in this repository), which does.
    """
    digest = _sha256_file(tarball)
    sums = tarball.parent / "SHA256SUMS"
    if not sums.is_file():
        raise SystemExit(f"intermediates: no SHA256SUMS beside {tarball.name}")
    # `digest  name` (text mode) or `digest *name` (sha256sum -b).
    listed = {ln.split()[1].removeprefix("*"): ln.split()[0]
              for ln in sums.read_text().splitlines() if len(ln.split()) == 2}
    if listed.get(tarball.name) != digest:
        raise SystemExit(f"intermediates: {tarball.name} does not match SHA256SUMS")
    if expect is not None and expect.lower() != digest:
        raise SystemExit(f"intermediates: {tarball.name} sha256 {digest} is not the "
                         f"expected {expect}")
    return digest


def unpack(tarball: Path, dest: Path) -> dict[str, Any]:
    """Extract regular files only, inside ``dest``; verify every manifest hash."""
    with tarfile.open(tarball, mode="r:gz") as tar:
        members = []
        names: set[str] = set()
        total = 0
        for m in tar:  # headers only; stops at the first bad member
            parts = Path(m.name).parts
            if not m.isfile() or m.name.startswith("/") or ".." in parts or not parts:
                raise SystemExit(f"intermediates: refusing tar member {m.name!r}")
            if m.name in names:
                raise SystemExit(f"intermediates: duplicate tar member {m.name!r}")
            names.add(m.name)
            total += m.size
            if (len(members) >= MAX_MEMBERS or m.size > MAX_MEMBER_BYTES
                    or total > MAX_TOTAL_BYTES):
                raise SystemExit("intermediates: tarball exceeds the unpack limits")
            members.append(m)
        for m in members:
            target = dest / m.name
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            assert src is not None
            with target.open("wb") as out:  # streamed, never whole in memory
                shutil.copyfileobj(src, out, 1 << 20)
    try:
        manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"intermediates: no readable {MANIFEST_NAME}: {exc}") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
            or not isinstance(files, dict)
            or not all(isinstance(v, dict) and isinstance(v.get("sha256"), str)
                       for v in files.values())):
        raise SystemExit(f"intermediates: {MANIFEST_NAME} is not a {SCHEMA} manifest")
    on_disk = {m.name for m in members} - {MANIFEST_NAME}
    if on_disk != set(files):
        raise SystemExit("intermediates: tarball members differ from MANIFEST.json")
    for arc, meta in files.items():
        if _sha256_file(dest / arc) != meta["sha256"]:  # streamed
            raise SystemExit(f"intermediates: {arc} does not match MANIFEST.json")
    return manifest


def _run(script: str, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PURSUE_")}
    env.pop("PYTHONPATH", None)
    done = subprocess.run([sys.executable, str(SCRIPTS_DIR / script), *args],
                          cwd=repo_root(), env=env, capture_output=True, text=True,
                          check=False)
    if done.returncode != 0:
        raise SystemExit(f"intermediates: {script} failed:\n{done.stderr or done.stdout}")
    print(f"  {script}: {(done.stdout.strip().splitlines() or [''])[-1]}")


def rebuild(root: Path, out: Path) -> None:
    """Run the three builders on an unpacked tarball, writing under ``out``."""
    ocr, emb = root / "ocr", root / "embeddings"
    out.mkdir(parents=True, exist_ok=True)
    _run("build_search_data.py", "--ocr-dir", str(ocr), "--out", str(out / "pages.json"))
    _run("build_pages_cleaned.py", "--ocr-dir", str(ocr), "--out",
         str(out / "pages-cleaned.json"), "--pages", str(out / "pages.json"))
    _run("build_embed_data.py", "--embeddings-root", str(emb), "--model", EMBED_MODEL,
         "--out-dir", str(out), "--pages-json", str(out / "pages.json"), "--ocr-dir", str(ocr))


def _strip_build_time(doc: Any) -> Any:
    if isinstance(doc, dict) and isinstance(doc.get("meta"), dict):
        doc = {**doc, "meta": {k: v for k, v in doc["meta"].items() if k != "generated_at"}}
    return doc


def _field_diff(committed: Any, rebuilt: Any) -> str:
    """A short account of how two payloads differ, by top-level row field."""
    rows_a = committed.get("pages") if isinstance(committed, dict) else committed
    rows_b = rebuilt.get("pages") if isinstance(rebuilt, dict) else rebuilt
    if not isinstance(rows_a, list) or not isinstance(rows_b, list):
        return "differs (not a row list)"
    if len(rows_a) != len(rows_b):
        return f"{len(rows_a)} committed rows vs {len(rows_b)} rebuilt"
    fields: collections.Counter[str] = collections.Counter()
    for a, b in zip(rows_a, rows_b, strict=True):
        if isinstance(a, dict) and isinstance(b, dict):
            fields.update(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    meta = ""
    if isinstance(committed, dict) and isinstance(rebuilt, dict):
        ma = _strip_build_time(committed).get("meta")
        mb = _strip_build_time(rebuilt).get("meta")
        if ma != mb:
            keys = sorted(k for k in set(ma or {}) | set(mb or {})
                          if (ma or {}).get(k) != (mb or {}).get(k))
            meta = f"; meta fields differ {keys}"
    return f"{len(rows_a)} rows; differing fields {dict(sorted(fields.items()))}{meta}"


def compare(out: Path, published: Path | None = None) -> list[str]:
    """``[]`` when every rebuilt payload equals the committed one."""
    published = published_dir() if published is None else published
    problems: list[str] = []
    for name in PAYLOADS:
        committed, rebuilt = published / name, out / name
        a, b = read_asset_bytes(committed), read_asset_bytes(rebuilt)
        if a == b:
            print(f"  {name}: identical ({len(a)} bytes, sha256 {sha256_bytes(a)[:16]})")
            continue
        if name.endswith(".json"):
            ja, jb = read_asset_json(committed), read_asset_json(rebuilt)
            if _strip_build_time(ja) == _strip_build_time(jb):
                print(f"  {name}: identical apart from its build timestamp")
                continue
            problems.append(f"{name}: {_field_diff(ja, jb)}")
        else:
            problems.append(f"{name}: bytes differ ({len(a)} committed, {len(b)} rebuilt)")
    return problems


def rebuild_check(tarball: Path, expect: str | None = None,
                  allow_unpinned: bool = False) -> int:
    if expect is None and not allow_unpinned:
        raise SystemExit("intermediates: pass --expect-sha256 (from the release notes), or "
                         "--allow-unpinned to accept SHA256SUMS alone, which only catches "
                         "corruption")
    # The builders (beside this script) and the payloads they are compared with
    # (repo_root()) must come from one checkout, or the check compares one
    # checkout's code with another's data.
    code_root, data_root = SCRIPTS_DIR.parent, repo_root().resolve()
    if code_root != data_root:
        raise SystemExit(f"intermediates: builders are from {code_root} but the "
                         f"committed payloads are from {data_root}; run from one checkout")
    with tempfile.TemporaryDirectory(prefix="intermediates-") as tmp:
        # Hash and unpack one private copy, so the file cannot change between
        # the hash check and the unpack.
        copy = Path(tmp) / tarball.name
        shutil.copyfile(tarball, copy)
        sums = tarball.parent / "SHA256SUMS"
        if sums.is_file():  # _check_sums refuses the copy when it is missing
            shutil.copyfile(sums, Path(tmp) / "SHA256SUMS")
        digest = _check_sums(copy, expect)
        print(f"intermediates: checking {tarball.name} (sha256 {digest})")
        root, out = Path(tmp) / "root", Path(tmp) / "out"
        manifest = unpack(copy, root)
        print(f"  unpacked {len(manifest['files'])} files; every hash matches MANIFEST.json")
        rebuild(root, out)
        problems = compare(out)
    if problems:
        print(f"intermediates: {len(problems)} payload(s) differ from the committed ones:")
        for line in problems:
            print(f"  {line}")
        return 1
    print("intermediates: every payload rebuilds from the tarball alone")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack", help="write intermediates-<label>.tar.gz and SHA256SUMS")
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--label", required=True, help="the release tag, e.g. v1.7.0")
    c = sub.add_parser("rebuild-check", help="rebuild the payloads from a tarball alone")
    c.add_argument("--tarball", type=Path, required=True)
    c.add_argument("--expect-sha256", default=None,
                   help="the tarball's sha256 from an independent source; fail on any other")
    c.add_argument("--allow-unpinned", action="store_true",
                   help="run without --expect-sha256 (SHA256SUMS then only catches corruption)")
    args = parser.parse_args(argv)
    if args.cmd == "pack":
        pack(args.data_root, args.out_dir, args.label)
        return 0
    return rebuild_check(args.tarball, args.expect_sha256, args.allow_unpinned)


if __name__ == "__main__":
    sys.exit(main())
