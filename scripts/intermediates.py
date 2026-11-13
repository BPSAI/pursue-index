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

# Code is loaded from where this script lives, never from the data root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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

from pursue_index.release.chunked_asset import read_asset_bytes, read_asset_json

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "web" / "public" / "data"
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
    for card_dir in sorted(p for p in ocr.iterdir() if p.is_dir()):
        for name in CARD_FILES:
            src = card_dir / name
            if src.is_file() and not src.is_symlink():
                out.append((f"ocr/{card_dir.name}/{name}", src))
    emb = data_root / "embeddings" / EMBED_MODEL
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
    listed = {ln.split()[1]: ln.split()[0] for ln in sums.read_text().splitlines()
              if len(ln.split()) == 2}
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
        total = 0
        for m in tar:  # headers only; stops at the first bad member
            parts = Path(m.name).parts
            if not m.isfile() or m.name.startswith("/") or ".." in parts or not parts:
                raise SystemExit(f"intermediates: refusing tar member {m.name!r}")
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
    manifest = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise SystemExit(f"intermediates: manifest schema {manifest.get('schema')!r}")
    on_disk = {m.name for m in members} - {MANIFEST_NAME}
    if on_disk != set(manifest["files"]):
        raise SystemExit("intermediates: tarball members differ from MANIFEST.json")
    for arc, meta in manifest["files"].items():
        if sha256_bytes((dest / arc).read_bytes()) != meta["sha256"]:
            raise SystemExit(f"intermediates: {arc} does not match MANIFEST.json")
    return manifest


def _run(script: str, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PURSUE_")}
    env["PYTHONPATH"] = str(REPO / "src")
    done = subprocess.run([sys.executable, str(REPO / "scripts" / script), *args],
                          cwd=REPO, env=env, capture_output=True, text=True, check=False)
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


def compare(out: Path, published: Path = PUBLISHED) -> list[str]:
    """``[]`` when every rebuilt payload equals the committed one."""
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


def rebuild_check(tarball: Path, expect: str | None = None) -> int:
    digest = _check_sums(tarball, expect)
    print(f"intermediates: checking {tarball.name} (sha256 {digest})")
    with tempfile.TemporaryDirectory(prefix="intermediates-") as tmp:
        root, out = Path(tmp) / "root", Path(tmp) / "out"
        manifest = unpack(tarball, root)
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
    args = parser.parse_args(argv)
    if args.cmd == "pack":
        pack(args.data_root, args.out_dir, args.label)
        return 0
    return rebuild_check(args.tarball, args.expect_sha256)


if __name__ == "__main__":
    sys.exit(main())
