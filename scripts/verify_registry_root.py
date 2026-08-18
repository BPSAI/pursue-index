"""Verify ``data/registry-root.txt`` matches the current registry.

Phase 2 (per
``pursue-opsec-staging/findings/2026-05-18-tier2-registry-signing-rfc.md``
§5.1 #2).

Two concerns this script handles:

1. **Root-file freshness.** Re-derive the Merkle root from the local
   ``data/asset-bytes-registry.jsonl`` and compare to whatever is
   recorded in ``data/registry-root.txt``. A mismatch means either
   (a) the operator edited the registry but forgot to re-run
   ``registry_root.py``, or (b) someone tampered with one of the two
   files. Either way: exit non-zero, file an issue.

2. **Divergence localization.** On mismatch, if the operator has
   provided a ``--signed-source`` (typically the registry bytes
   recoverable from the latest signed ``registry-root-*`` git tag
   via ``git show <tag>:data/asset-bytes-registry.jsonl``), the
   verifier walks the leaf hashes of both states and reports the
   first divergent row index + the row count delta. Lets the
   operator jump straight to the tampered row instead of
   git-diffing 230+ lines by hand.

Signature verification (``git tag -v``) is NOT this script's job —
it's a single-line step in ``verify-assets-daily.yml`` (Phase 4).
Keeping the two concerns separate means the workflow can react
differently to a "root drift" failure (operator forgot to refresh)
vs. a "signature failure" (key compromise or unsigned tampering).

Exit codes:
  0 — root matches; registry integrity confirmed against
      ``registry-root.txt`` (whatever that file's contents have been
      attested to — see the signature-verify lane for that side).
  1 — mismatch, missing root file, corrupt root file. Workflow
      should file a ``registry-root-mismatch`` issue.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from registry_root import (  # noqa: E402
    canonicalize_row,
    compute_registry_root,
    leaf_hash,
    read_registry_rows,
)

_REPO_ROOT = _SCRIPTS_DIR.parent
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_ROOT = _REPO_ROOT / "data" / "registry-root.txt"

# 64-hex sanity check on the stored root file.
_HEX_ROOT_RE = re.compile(r"^[0-9a-f]{64}$")


def read_root_file(root_path: Path) -> str | None:
    """Return the 64-hex stored root, or None if missing/corrupt."""
    try:
        contents = root_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return contents if _HEX_ROOT_RE.match(contents) else None


def find_first_divergent_index(
    current: list[bytes], expected: list[bytes]
) -> int | None:
    """Return the index of the first position where the two leaf lists
    differ, or None if they're identical up to ``min(len)`` AND the
    same length. When current is shorter, returns ``len(current)``
    (the position where current ran out) — that's also "different"
    semantically.
    """
    for i, (cur, exp) in enumerate(zip(current, expected)):
        if cur != exp:
            return i
    if len(current) != len(expected):
        return min(len(current), len(expected))
    return None


def _leaves_from_registry(registry_path: Path) -> list[bytes]:
    rows = read_registry_rows(registry_path)
    return [leaf_hash(canonicalize_row(row)) for row in rows]


def _report_divergence(
    *, current_registry: Path, signed_source: Path
) -> None:
    """Walk the two leaf lists and surface the first divergent index +
    row counts. Side-effects: ``print()`` only.

    Catches malformed signed-source bytes — `git show
    <tag>:...` output can be partially truncated by a network blip
    or a buggy redirect. Don't crash; degrade to "row counts only"
    with a clear warning.
    """
    try:
        current_leaves = _leaves_from_registry(current_registry)
    except ValueError as exc:
        print(f"::warning::current registry is malformed; cannot locate divergence: {exc}")
        return
    try:
        expected_leaves = _leaves_from_registry(signed_source)
    except ValueError as exc:
        print(
            f"::warning::signed-source {signed_source} is malformed JSON,"
            f" skipping divergence locator: {exc}"
        )
        return
    idx = find_first_divergent_index(current_leaves, expected_leaves)
    print(
        f"registry row count: current={len(current_leaves)},"
        f" signed={len(expected_leaves)}"
    )
    if idx is None:
        # Identical leaves but root file mismatched — the root file
        # itself is the tampering vector. Surface it explicitly.
        print(
            "leaves match between current and signed registry —"
            " registry-root.txt is the source of the mismatch"
            " (tampered or stale recorded root)"
        )
        return
    print(f"first divergent row: index {idx} (0-based)")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--signed-source",
        default="",
        help=(
            "Path to a file containing the registry bytes recoverable"
            " from the latest signed registry-root-* git tag (i.e.,"
            " `git show <tag>:data/asset-bytes-registry.jsonl >"
            " /tmp/signed.jsonl`). Empty string skips divergence"
            " localization — appropriate before the operator has signed"
            " the baseline tag."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    stored = read_root_file(args.root)
    if stored is None:
        print(
            f"::error::registry-root.txt missing or malformed at {args.root};"
            " re-run scripts/registry_root.py to refresh"
        )
        return 1
    try:
        recomputed, row_count, first_ts, last_ts = compute_registry_root(args.registry)
    except FileNotFoundError:
        # A missing registry file gets a stack trace today. Surface
        # as an actionable ::error:: instead so the operator can fix
        # --registry pathing without parsing a traceback.
        print(
            f"::error::registry file not found at {args.registry};"
            " check --registry path"
        )
        return 1
    except ValueError as exc:
        # Malformed JSON in the registry — surface row number from
        # the underlying error.
        print(f"::error::registry is malformed: {exc}")
        return 1
    if stored == recomputed:
        print(
            f"::notice::registry-root verified: {stored[:12]}... over"
            f" {row_count} rows ({first_ts} → {last_ts})"
        )
        return 0
    print(
        f"::error::registry-root mismatch: stored={stored[:16]}...,"
        f" recomputed={recomputed[:16]}... — the registry was edited"
        " without refreshing registry-root.txt, OR one of the two"
        " files has been tampered with"
    )
    signed_source = args.signed_source
    if not signed_source:
        print(
            "::warning::no signed registry source provided — skipping"
            " divergence locator. Sign the baseline registry-root-* tag"
            " to enable per-row drift attribution on future verifies."
        )
        return 1
    signed_path = Path(signed_source)
    if not signed_path.is_file():
        print(
            f"::warning::signed-source path {signed_path} does not exist;"
            " skipping divergence locator"
        )
        return 1
    _report_divergence(current_registry=args.registry, signed_source=signed_path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
