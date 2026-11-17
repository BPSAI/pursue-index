#!/usr/bin/env python3
"""Attach a packed intermediates archive to a tag's Release, after checking it.

    python scripts/release_intermediates.py --tag vX.Y.Z --dir <out dir> [--root .]

``<out dir>`` is where ``make ship-ready INTERMEDIATES_LABEL=vX.Y.Z`` packed
``intermediates-<tag>.tar.gz`` and its ``SHA256SUMS``. Before uploading, this
refuses (non-zero, with the reason) unless:

1. the tarball exists and matches ``SHA256SUMS``;
2. the build stamp committed at ``HEAD`` pins this tarball's sha256 (the check
   ``build_stamp.py verify --intermediates`` makes, against the committed
   stamp, not a working-tree edit of it);
3. no packed QC sidecar row still carries a field the pack drops;
4. ``HEAD`` is the tag's commit, so the stamp that vouches is the release's own.

Only then does it run ``gh release upload <tag> <tarball> <SHA256SUMS>``. It
never creates the Release, edits its notes, or replaces an existing asset
(no ``--clobber``): an asset already on the Release makes ``gh`` refuse, and
replacing it is a deliberate manual act. On success it prints the
``SHA256SUMS`` line to paste into the release notes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _intermediates_scrub import QC_DROP_FIELDS, QC_SIDECAR
from build_stamp import STAMP_PATH, archive_problems, intermediates_problems
from intermediates import _check_sums

TAG = re.compile(r"v\d+\.\d+\.\d+")

Runner = Callable[[list[str]], int]


def run_upload(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def head_stamp(root: Path) -> dict:
    """The build stamp as committed at ``HEAD`` in ``root``."""
    shown = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{STAMP_PATH}"],
                           capture_output=True, text=True, check=False)
    if shown.returncode != 0:
        raise SystemExit(f"release-intermediates: no {STAMP_PATH} at HEAD")
    try:
        stamp = json.loads(shown.stdout)
    except ValueError as exc:
        raise SystemExit(f"release-intermediates: {STAMP_PATH} at HEAD is not JSON") from exc
    if not isinstance(stamp, dict):
        raise SystemExit(f"release-intermediates: {STAMP_PATH} at HEAD is not an object")
    return stamp


def dropped_field_rows(tarball: Path) -> list[str]:
    """``member:line`` for every packed QC row that still carries a dropped field."""
    hits = []
    with tarfile.open(tarball, mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(f"/{QC_SIDECAR}"):
                continue
            src = tar.extractfile(member)
            assert src is not None
            for n, line in enumerate(src, 1):
                try:
                    row = json.loads(line) if line.strip() else None
                except ValueError as exc:
                    raise SystemExit(f"release-intermediates: {member.name}:{n} "
                                     "is not JSON") from exc
                if isinstance(row, dict) and any(f in row for f in QC_DROP_FIELDS):
                    hits.append(f"{member.name}:{n}")
    return hits


def head_tag_problem(root: Path, tag: str) -> str | None:
    """Why ``HEAD`` in ``root`` is not the tagged release, or ``None`` if it is.

    The stamp that pins the archive is read at ``HEAD``, so ``HEAD`` must be
    the tag's commit, or another release's stamp could vouch for this upload.
    """
    def rev(ref: str) -> str | None:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                              f"{ref}^{{commit}}"], capture_output=True, text=True, check=False)
        return out.stdout.strip() if out.returncode == 0 else None

    tagged = rev(f"refs/tags/{tag}")
    if tagged is None:
        return f"no tag {tag} in {root}; fetch tags first"
    if rev("HEAD") != tagged:
        return f"HEAD is not {tag}; check out the tag before attaching its archive"
    return None


def release(tag: str, out_dir: Path, root: Path, run: Runner | None = None) -> int:
    if not TAG.fullmatch(tag):
        raise SystemExit(f"release-intermediates: tag {tag!r} is not vX.Y.Z")
    tarball = out_dir / f"intermediates-{tag}.tar.gz"
    sums = out_dir / "SHA256SUMS"
    if not tarball.is_file():
        raise SystemExit(f"release-intermediates: {tarball} not found")
    digest = _check_sums(tarball)
    stamp = head_stamp(root)
    found = intermediates_problems(stamp) or archive_problems(stamp, tarball)
    if found:
        raise SystemExit("release-intermediates: the stamp at HEAD does not pin "
                         f"{tarball.name}: {'; '.join(found)}")
    leaked = dropped_field_rows(tarball)
    if leaked:
        raise SystemExit(f"release-intermediates: {len(leaked)} packed QC row(s) still carry "
                         f"{', '.join(QC_DROP_FIELDS)}: {', '.join(leaked[:5])}")
    problem = head_tag_problem(root, tag)
    if problem:
        raise SystemExit(f"release-intermediates: {problem}")
    argv = ["gh", "release", "upload", tag, str(tarball), str(sums)]
    rc = (run or run_upload)(argv)
    if rc != 0:
        print(f"release-intermediates: upload failed (exit {rc})", file=sys.stderr)
        return rc
    print(f"release-intermediates: attached {tarball.name} and SHA256SUMS to {tag}")
    print("Paste into the release notes:")
    print(f"{digest}  {tarball.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", required=True, help="the Release's tag, vX.Y.Z")
    parser.add_argument("--dir", type=Path, required=True,
                        help="the directory holding the tarball and SHA256SUMS")
    parser.add_argument("--root", type=Path, default=Path("."),
                        help="the checkout whose HEAD stamp must pin the tarball")
    args = parser.parse_args(argv)
    return release(args.tag, args.dir, args.root)


if __name__ == "__main__":
    sys.exit(main())
