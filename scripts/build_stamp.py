#!/usr/bin/env python3
"""Write or verify ``data/build-stamp.json``, the promote bundle's digest record.

The build writes the approved content into a checkout of the site
repository (pursue-index). The stamp records, for every bundle file, its
sha256, plus the builder's commit, so the site can prove that what it is about
to publish is exactly what the build wrote:

    python scripts/build_stamp.py write  --root <index checkout> --builder-commit <sha>
    python scripts/build_stamp.py verify --root <index checkout> [--require]

The bundle is every git-tracked file under ``BUNDLE_ROOTS`` except code
(``EXCLUDED``, two fixed code files). Hand-authored editorial content (finds) is not
bundle: it is reviewed in its own pull requests.

``verify`` fails (exit 1) when a stamped file is missing or its bytes differ,
or a bundle file is not in the stamp. Without a stamp it passes with a notice,
unless ``--require`` (the stamp becomes mandatory once every promote writes one).

Standard library only, and byte-identical in the build repository (writer)
and the site repository (verifier), so either can run it without the other's
dependencies. The stamp names no repository and no internal path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

SCHEMA = "pursue-build-stamp/v1"
STAMP_PATH = "data/build-stamp.json"
BUNDLE_ROOTS = (
    "data/manifests",
    "data/card-aliases.json",
    "data/display_dates.json",
    "web/src/data",
    "web/public/data",
    "web/public/llms.txt",
    "web/public/llms-full.txt",
)
# The only code under the bundle roots, named exactly: any other file there,
# whatever its suffix, is bundle and must be stamped.
EXCLUDED = frozenset({"web/src/data/manifest-loader.ts", "web/src/data/types.ts"})
_SHA1 = re.compile(r"[0-9a-f]{40}")


def bundle_files(root: Path) -> list[str]:
    """Tracked bundle paths under ``root``, sorted, POSIX-relative."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", *BUNDLE_ROOTS],
        capture_output=True, check=True,
    ).stdout.decode("utf-8")
    return sorted(p for p in out.split("\0") if p and p not in EXCLUDED)


def is_bundle_path(rel: object) -> bool:
    """A stamp key is a relative POSIX path, with no ``..`` and no empty or
    ``.`` parts, inside one of ``BUNDLE_ROOTS`` and not excluded code."""
    if not isinstance(rel, str) or not rel or "\\" in rel or "\0" in rel:
        return False
    parts = PurePosixPath(rel).parts
    if rel.startswith("/") or any(p in ("", ".", "..") for p in rel.split("/")):
        return False
    if rel in EXCLUDED:
        return False
    return any(rel == r or rel.startswith(r + "/") for r in BUNDLE_ROOTS) and bool(parts)


def _inside(root: Path, path: Path) -> bool:
    """True when ``path``, with every symlinked parent resolved, stays in ``root``."""
    return path.resolve().is_relative_to(root.resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(root: Path, builder_commit: str) -> dict:
    if not _SHA1.fullmatch(builder_commit):
        raise ValueError(f"--builder-commit must be a 40-hex commit sha, got {builder_commit!r}")
    links = [rel for rel in bundle_files(root)
             if (root / rel).is_symlink() or not _inside(root, root / rel)]
    if links:
        raise ValueError(f"bundle files must be regular files, not symlinks: {links[:5]}")
    files = {rel: sha256_file(root / rel) for rel in bundle_files(root)}
    return {"schema": SCHEMA, "builder_commit": builder_commit, "files": files}


def problems(root: Path, stamp: dict) -> list[str]:
    """Why ``stamp`` does not describe ``root``'s bundle; ``[]`` when it does."""
    if stamp.get("schema") != SCHEMA:
        return [f"stamp schema is {stamp.get('schema')!r}, expected {SCHEMA!r}"]
    commit = stamp.get("builder_commit")
    if not isinstance(commit, str) or not _SHA1.fullmatch(commit):
        return ["stamp builder_commit is not a 40-hex commit sha"]
    stamped = stamp.get("files")
    if not isinstance(stamped, dict):
        return ["stamp has no files object"]
    out: list[str] = []
    for rel in sorted(stamped):
        if not is_bundle_path(rel):
            # Never touch the filesystem for a key that could leave the checkout.
            out.append(f"not a bundle path: {rel!r}")
            continue
        path = root / rel
        if path.is_symlink() or not _inside(root, path):
            out.append(f"symlink, not a file: {rel}")
        elif not path.is_file():
            out.append(f"missing: {rel}")
        elif sha256_file(path) != stamped[rel]:
            out.append(f"changed since the build: {rel}")
    out += [f"not in the stamp: {rel}" for rel in bundle_files(root) if rel not in stamped]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="stamp the bundle in a pursue-index checkout")
    w.add_argument("--root", type=Path, required=True)
    w.add_argument("--builder-commit", required=True)
    v = sub.add_parser("verify", help="check a checkout's bundle against its stamp")
    v.add_argument("--root", type=Path, default=Path("."))
    v.add_argument("--require", action="store_true", help="fail when there is no stamp")
    args = parser.parse_args(argv)

    stamp_file = args.root / STAMP_PATH
    if args.cmd == "write":
        stamp = build(args.root, args.builder_commit)
        stamp_file.write_text(json.dumps(stamp, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"build-stamp: {len(stamp['files'])} bundle files stamped -> {STAMP_PATH}")
        return 0

    if not stamp_file.is_file():
        if args.require:
            print(f"build-stamp: refused, no {STAMP_PATH}", file=sys.stderr)
            return 1
        print(f"build-stamp: no {STAMP_PATH} yet; nothing to verify (not yet required)")
        return 0
    found = problems(args.root, json.loads(stamp_file.read_text(encoding="utf-8")))
    if found:
        print(f"build-stamp: {len(found)} problem(s):", file=sys.stderr)
        for line in found[:50]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"build-stamp: bundle matches {STAMP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
