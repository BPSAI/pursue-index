#!/usr/bin/env python3
"""Write or verify ``data/build-stamp.json``, the promote bundle's digest record.

The release build (``make ship-ready``) writes the approved content into this
checkout. The stamp records, for every bundle file, its sha256, plus the commit
of this repository whose code built it, so anyone can prove that what is about
to be published is exactly what that code wrote, and can check out that commit:

    python scripts/build_stamp.py write  --root . --builder-commit <sha> [--intermediates <tarball>]
    python scripts/build_stamp.py verify --root . [--require] [--public-ref origin/main]
                                         [--intermediates <tarball>]

The bundle is every file under ``BUNDLE_ROOTS`` that git tracks or would add
(untracked, not ignored) except code
(``EXCLUDED``, two fixed code files). Hand-authored editorial content (finds) is not
bundle: it is reviewed in its own pull requests.

``verify`` fails (exit 1) when a stamped file is missing or its bytes differ,
or a bundle file is not in the stamp. Without a stamp it passes with a notice,
unless ``--require``. With ``--public-ref``, it also fails unless the builder
commit is in this repository and is an ancestor of that ref (the published
branch), so the stamp never cites code a reader cannot fetch.

The stamp may also pin the release's intermediates archive (see
``docs/intermediates.md``) under an optional ``intermediates`` key,
``{"name": "intermediates-<tag>.tar.gz", "sha256": "<64 hex>"}``, written by
``write --intermediates``. Stamps without it stay valid; a malformed one fails
``verify``. ``verify --intermediates <tarball>`` also fails unless the stamp
has the key and the tarball's sha256 matches it.

Standard library only. The stamp names no repository and no internal path.
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
_SHA256 = re.compile(r"[0-9a-f]{64}")
# The label rule of ``intermediates.py pack``: non-empty, no ``/``, no leading
# ``.``; backslashes and control characters are refused too.
_ARCHIVE_NAME = re.compile(r"intermediates-(?!\.)[^/\\\x00-\x1f\x7f]+\.tar\.gz")


def bundle_files(root: Path) -> list[str]:
    """Bundle paths under ``root``, sorted, POSIX-relative.

    Tracked files plus untracked ones that are not gitignored: a release writes
    new bundle files (a new manifest snapshot, say) before they are committed,
    and the commit adds them, so the stamp must cover them already. Tracked
    paths deleted from the working tree are left out, as the commit removes
    them.
    """
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
         "--exclude-standard", "--", *BUNDLE_ROOTS],
        capture_output=True, check=True,
    ).stdout.decode("utf-8")
    paths = {p for p in out.split("\0") if p and p not in EXCLUDED}
    return sorted(p for p in paths if (root / p).is_symlink() or (root / p).exists())


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


def intermediates_entry(tarball: Path) -> dict:
    """The stamp's ``intermediates`` value for ``tarball``: its name and sha256."""
    if not _ARCHIVE_NAME.fullmatch(tarball.name):
        raise ValueError(f"--intermediates must be an intermediates-<tag>.tar.gz file, "
                         f"got {tarball.name!r}")
    return {"name": tarball.name, "sha256": sha256_file(tarball)}


def intermediates_problems(stamp: dict) -> list[str]:
    """Why the stamp's optional ``intermediates`` key is malformed; ``[]`` when
    it is absent or well formed."""
    if "intermediates" not in stamp:
        return []
    entry = stamp["intermediates"]
    if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
        return ["stamp intermediates is not an object with exactly name and sha256"]
    name, sha = entry["name"], entry["sha256"]
    out = []
    if not isinstance(name, str) or not _ARCHIVE_NAME.fullmatch(name):
        out.append(f"stamp intermediates name {name!r} is not intermediates-<tag>.tar.gz")
    if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
        out.append("stamp intermediates sha256 is not a 64-hex sha256")
    return out


def archive_problems(stamp: dict, tarball: Path) -> list[str]:
    """Why ``tarball`` is not the archive ``stamp`` pins; ``[]`` when it is."""
    entry = stamp.get("intermediates")
    if entry is None:
        return ["stamp has no intermediates key; cannot check the archive against it"]
    if not tarball.is_file():
        return [f"intermediates archive not found: {tarball}"]
    actual = sha256_file(tarball)
    if actual != entry["sha256"]:
        return [f"intermediates archive sha256 {actual} differs from the stamped "
                f"{entry['sha256']} ({entry['name']})"]
    return []


def build(root: Path, builder_commit: str, intermediates: Path | None = None) -> dict:
    if not _SHA1.fullmatch(builder_commit):
        raise ValueError(f"--builder-commit must be a 40-hex commit sha, got {builder_commit!r}")
    links = [rel for rel in bundle_files(root)
             if (root / rel).is_symlink() or not _inside(root, root / rel)]
    if links:
        raise ValueError(f"bundle files must be regular files, not symlinks: {links[:5]}")
    entry = intermediates_entry(intermediates) if intermediates is not None else None
    files = {rel: sha256_file(root / rel) for rel in bundle_files(root)}
    stamp = {"schema": SCHEMA, "builder_commit": builder_commit, "files": files}
    if entry is not None:
        stamp["intermediates"] = entry
    return stamp


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
    out = intermediates_problems(stamp)
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


def commit_problems(root: Path, commit: str, public_ref: str) -> list[str]:
    """Why ``commit`` is not public code in ``root``; ``[]`` when it is an
    existing commit and an ancestor of ``public_ref``."""
    if not _SHA1.fullmatch(commit):  # never hand git a ref name or an option
        return [f"builder commit {commit!r} is not a 40-hex commit sha"]
    git = ["git", "-C", str(root)]
    exists = subprocess.run([*git, "cat-file", "-e", f"{commit}^{{commit}}"],
                            capture_output=True, check=False)
    if exists.returncode != 0:
        return [f"builder commit {commit} is not a commit in this repository"]
    if not public_ref or public_ref.startswith("-"):  # a ref, never an option
        return [f"public ref {public_ref!r} is not a ref name"]
    ancestor = subprocess.run([*git, "merge-base", "--is-ancestor", commit, public_ref],
                              capture_output=True, text=True, check=False)
    if ancestor.returncode == 1:
        return [f"builder commit {commit} is not on {public_ref}"]
    if ancestor.returncode != 0:
        return [f"cannot check builder commit against {public_ref}: "
                f"{ancestor.stderr.strip() or 'git failed'}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="stamp the bundle in this checkout")
    w.add_argument("--root", type=Path, required=True)
    w.add_argument("--builder-commit", required=True)
    w.add_argument("--intermediates", type=Path, default=None,
                   help="also pin this intermediates-<tag>.tar.gz by name and sha256")
    v = sub.add_parser("verify", help="check a checkout's bundle against its stamp")
    v.add_argument("--root", type=Path, default=Path("."))
    v.add_argument("--require", action="store_true", help="fail when there is no stamp")
    v.add_argument("--public-ref", default=None,
                   help="fail unless the builder commit is an ancestor of this ref")
    v.add_argument("--intermediates", type=Path, default=None,
                   help="fail unless this tarball's sha256 is the stamped one")
    args = parser.parse_args(argv)

    stamp_file = args.root / STAMP_PATH
    if args.cmd == "write":
        stamp = build(args.root, args.builder_commit, args.intermediates)
        stamp_file.write_text(json.dumps(stamp, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"build-stamp: {len(stamp['files'])} bundle files stamped -> {STAMP_PATH}")
        return 0

    if not stamp_file.is_file():
        if args.require or args.intermediates is not None:
            print(f"build-stamp: refused, no {STAMP_PATH}", file=sys.stderr)
            return 1
        print(f"build-stamp: no {STAMP_PATH} yet; nothing to verify (not yet required)")
        return 0
    stamp = json.loads(stamp_file.read_text(encoding="utf-8"))
    found = problems(args.root, stamp)
    if not found and args.public_ref:
        found = commit_problems(args.root, stamp["builder_commit"], args.public_ref)
    if not found and args.intermediates is not None:
        found = archive_problems(stamp, args.intermediates)
    if found:
        print(f"build-stamp: {len(found)} problem(s):", file=sys.stderr)
        for line in found[:50]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"build-stamp: bundle matches {STAMP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
