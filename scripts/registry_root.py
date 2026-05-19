"""Merkle-root commitment over ``data/asset-bytes-registry.jsonl``.

Sprint 4e Phase 1 (per
``pursue-opsec-staging/findings/2026-05-18-tier2-registry-signing-rfc.md``).

The registry is a JSONL log of every preserved asset's
``byte_sha256`` + ``archive_key``. Tier-1 (the daily byte-verify cron)
defends against R2 mutation of the preserved copy. Tier-2 — this
script + an operator-signed git tag per promote — defends against
mutation of the *registry itself* by an attacker who can write to
main.

Pipeline:

1. Read ``data/asset-bytes-registry.jsonl`` line-by-line.
2. Canonicalize each row (sort_keys + compact separators + utf-8).
3. Hash each canonical row to a 32-byte leaf (sha256).
4. Build a binary Merkle tree over the leaves in file order.
   Odd-count levels duplicate the last node (Bitcoin-style).
5. Write the 64-hex root to ``data/registry-root.txt``.
6. Write a tab-separated receipt to
   ``data/registry-root-manifest.txt`` recording
   ``<root>\\t<row_count>\\t<first_fetched_at>\\t<last_fetched_at>``.

The operator then signs the commit that bumps these files via
``git tag -s registry-root-YYYY-MM-DD-HHMM <commit_sha>``. The
signature transitively commits to the root because the tag's tree
includes ``registry-root.txt``.

Idempotent: same registry → byte-identical output across re-runs and
across machines. This is the load-bearing property the signed tag
commits to — drift here means a future verifier reports a false
mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "asset-bytes-registry.jsonl"
DEFAULT_ROOT = _REPO_ROOT / "data" / "registry-root.txt"
DEFAULT_MANIFEST = _REPO_ROOT / "data" / "registry-root-manifest.txt"


# RFC 6962 (Certificate Transparency) domain-separation prefixes.
# Leaves are hashed with 0x00 prepended; internal nodes are hashed
# with 0x01 prepended. This defeats the Bitcoin-style 2nd-preimage
# attack (CVE-2012-2459) where a registry of N rows and a registry
# of N+1 rows formed by duplicating the last leaf can produce the
# same Merkle root.
_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


def canonicalize_row(row: dict) -> bytes:
    """Deterministic canonical encoding of a single registry row.

    ``sort_keys=True`` removes key-order ambiguity. Compact separators
    strip whitespace so the bytes are exact. ``ensure_ascii=False``
    preserves any non-ASCII codepoints literally — escaping them to
    ``\\uXXXX`` would make canonical bytes Python-version-sensitive
    (escapes lowercase changed across versions historically).
    ``allow_nan=False`` rejects ``NaN``/``Infinity`` — non-standard
    JSON, Python-only, cross-verifier-fatal (laverna P2). UTF-8
    encoding lands the final bytes.

    Compatible with RFC 8785 on the subset of types this registry
    uses today (``str``/``int``/``bool`` only). Future schema
    extensions adding ``float``/``Decimal``/``null`` numeric values
    would need to revisit this encoding choice.
    """
    return json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def leaf_hash(canonical_bytes: bytes) -> bytes:
    """RFC 6962 leaf hash: sha256(0x00 || canonical). Returns 32 raw
    bytes. The 0x00 prefix is what separates "leaf semantics" from
    "internal-node semantics" so an attacker can't repurpose internal
    bytes as leaves (or vice versa)."""
    return hashlib.sha256(_LEAF_PREFIX + canonical_bytes).digest()


def build_merkle_root(leaves: list[bytes]) -> bytes:
    """RFC 6962 §2.1 Merkle Hash. Split at the largest power of 2
    strictly less than ``len(leaves)``, recurse on each half, combine
    with the internal-node prefix. NO duplicate-last — odd subtree
    sizes are handled by the recursive split, which is what defeats
    the Bitcoin 2nd-preimage attack.

    Refuses empty input — a Merkle root over nothing is meaningless
    and almost certainly an operator mistake.
    """
    if not leaves:
        raise ValueError("cannot build Merkle root over empty leaf list")
    if len(leaves) == 1:
        return leaves[0]
    # Largest power of 2 strictly less than n.
    n = len(leaves)
    k = 1
    while k * 2 < n:
        k *= 2
    left = build_merkle_root(leaves[:k])
    right = build_merkle_root(leaves[k:])
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


def read_registry_rows(registry_path: Path) -> list[dict]:
    """Parse JSONL, skipping blank lines (file-tail whitespace is not
    data). Raises ValueError with a row number on the first malformed
    line so the operator can fix it without scanning the whole file.

    Public per nayru M2.1 — the verifier module depends on this
    contract.
    """
    rows: list[dict] = []
    text = registry_path.read_text(encoding="utf-8")
    # ``row_no`` counts only non-blank lines; the error message uses
    # that number so it matches the row position the operator sees in
    # a JSONL-aware viewer.
    row_no = 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        row_no += 1
        try:
            rows.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"asset-bytes-registry.jsonl row {row_no} is not valid JSON: {exc}"
            ) from exc
    return rows


def _fetched_at_or_unknown(row: dict) -> str:
    """Return ``row['fetched_at']`` if it's a non-empty string, else
    ``(unknown)``. Distinct from ``.get(default=...)`` because we
    want explicit-null in the registry to map to ``(unknown)``, not
    to the literal string ``"None"`` (nayru M1.3).
    """
    value = row.get("fetched_at")
    return value if isinstance(value, str) and value else "(unknown)"


def compute_registry_root(registry_path: Path) -> tuple[str, int, str, str]:
    """Read the registry and produce a (root_hex, row_count,
    first_fetched_at, last_fetched_at) tuple. The tuple maps directly
    to the manifest-receipt format. Timestamps are positional (first
    row in file, last row in file) — the registry isn't sorted by
    fetched_at and the receipt's column names are *not* min/max.
    """
    rows = read_registry_rows(registry_path)
    leaves = [leaf_hash(canonicalize_row(row)) for row in rows]
    root = build_merkle_root(leaves)
    first_ts = _fetched_at_or_unknown(rows[0]) if rows else "(unknown)"
    last_ts = _fetched_at_or_unknown(rows[-1]) if rows else "(unknown)"
    return root.hex(), len(rows), first_ts, last_ts


def write_root_files(
    *,
    root_hex: str,
    row_count: int,
    first_ts: str,
    last_ts: str,
    root_path: Path,
    manifest_path: Path,
) -> None:
    """Write the two output files. Atomic-write via temp + rename so a
    crash mid-write can't leave a half-flushed root file lying around
    (mirrors the wayback_save M1 fix-pass from Sprint 4a)."""
    root_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(root_path, root_hex + "\n")
    manifest_line = f"{root_hex}\t{row_count}\t{first_ts}\t{last_ts}\n"
    _atomic_write_text(manifest_path, manifest_line)


def _atomic_write_text(path: Path, content: str) -> None:
    # encoding=utf-8 explicit per project convention + nayru M1.4 —
    # platform default is utf-8 on the runner but explicit pins the
    # contract against a future runner-image change.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root_hex, row_count, first_ts, last_ts = compute_registry_root(args.registry)
    write_root_files(
        root_hex=root_hex,
        row_count=row_count,
        first_ts=first_ts,
        last_ts=last_ts,
        root_path=args.root,
        manifest_path=args.manifest,
    )
    print(
        f"registry-root: {root_hex[:12]}... over {row_count} rows"
        f" ({first_ts} → {last_ts})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
