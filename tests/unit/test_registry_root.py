"""Tests for ``scripts/registry_root.py`` — Merkle-root commitment over
``data/asset-bytes-registry.jsonl``.

The script canonicalizes each registry row, hashes
each canonical encoding to a leaf, builds a binary Merkle tree
(duplicate-last for odd counts, Bitcoin-style), and writes the root +
a human-readable manifest to ``data/registry-root.txt`` +
``data/registry-root-manifest.txt``.

Tests pin every invariant the verifier + the workflow will assume:

* Canonical row encoding is deterministic and stable (sort_keys +
  separators + utf-8 round-trip).
* Leaf hash = sha256(canonical_row_bytes).
* Merkle root construction is correct for 1/2/3/4/odd/even counts.
* Identical registries on different machines produce byte-identical
  root files — this is the load-bearing property the signed tag
  commits to.
* Re-running on the same registry is idempotent (root files don't
  drift across re-runs).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import registry_root as rr  # noqa: E402


# --------------------------- canonicalize_row -------------------------------


def test_canonicalize_row_sorts_keys() -> None:
    """Different key orderings must produce identical canonical bytes."""
    row_a = {"card_id": "abc", "byte_sha256": "11" * 32, "fetched_at": "2026-05-12T00:00:00Z"}
    row_b = {"fetched_at": "2026-05-12T00:00:00Z", "byte_sha256": "11" * 32, "card_id": "abc"}
    assert rr.canonicalize_row(row_a) == rr.canonicalize_row(row_b)


def test_canonicalize_row_uses_compact_separators() -> None:
    """No whitespace in canonical encoding — bytes must be exact."""
    row = {"a": 1, "b": 2}
    canonical = rr.canonicalize_row(row)
    assert b" " not in canonical
    assert canonical == b'{"a":1,"b":2}'


def test_canonicalize_row_preserves_unicode() -> None:
    """ensure_ascii=False so a row containing a non-ASCII byte (rare
    but possible in filenames) doesn't get escaped to \\uXXXX."""
    row = {"asset_filename": "naïve.pdf"}
    canonical = rr.canonicalize_row(row)
    # The actual unicode codepoint must round-trip, not an escape.
    assert "naïve.pdf".encode("utf-8") in canonical
    assert b"\\u" not in canonical


def test_canonicalize_row_returns_bytes_not_str() -> None:
    """The leaf hash takes bytes; the boundary is here, not in callers."""
    assert isinstance(rr.canonicalize_row({"x": 1}), bytes)


# --------------------------- leaf_hash + merkle ----------------------------


def test_leaf_hash_uses_rfc_6962_domain_separation() -> None:
    """RFC 6962 §2.1: leaf hashes are prefixed with 0x00 to defeat
    second-preimage attacks where a leaf could be confused with an
    internal node (Bitcoin CVE-2012-2459).
    """
    row = {"k": "v"}
    canonical = rr.canonicalize_row(row)
    expected = hashlib.sha256(b"\x00" + canonical).digest()
    assert rr.leaf_hash(canonical) == expected


def test_merkle_root_single_leaf_equals_that_leaf() -> None:
    """RFC 6962 §2.1: single-leaf tree's root IS the leaf hash."""
    leaf = rr.leaf_hash(b"only")
    assert rr.build_merkle_root([leaf]) == leaf


def test_merkle_root_two_leaves_uses_internal_node_prefix() -> None:
    """RFC 6962 §2.1: internal nodes prefix with 0x01."""
    leaf_a = rr.leaf_hash(b"a")
    leaf_b = rr.leaf_hash(b"b")
    expected = hashlib.sha256(b"\x01" + leaf_a + leaf_b).digest()
    assert rr.build_merkle_root([leaf_a, leaf_b]) == expected


def test_merkle_root_three_leaves_rfc_6962_split() -> None:
    """RFC 6962 §2.1 split: an odd-leaf tree splits at the largest
    power of 2 less than the leaf count. For 3 leaves: split at 2,
    left subtree = root([a,b]), right subtree = c (single leaf).
    NO duplication — that's the whole point of RFC 6962 over the
    Bitcoin construction.
    """
    a = rr.leaf_hash(b"a")
    b = rr.leaf_hash(b"b")
    c = rr.leaf_hash(b"c")
    left = hashlib.sha256(b"\x01" + a + b).digest()
    right = c
    expected = hashlib.sha256(b"\x01" + left + right).digest()
    assert rr.build_merkle_root([a, b, c]) == expected


def test_merkle_root_four_leaves_is_balanced() -> None:
    leaves = [rr.leaf_hash(s) for s in (b"a", b"b", b"c", b"d")]
    ab = hashlib.sha256(b"\x01" + leaves[0] + leaves[1]).digest()
    cd = hashlib.sha256(b"\x01" + leaves[2] + leaves[3]).digest()
    expected = hashlib.sha256(b"\x01" + ab + cd).digest()
    assert rr.build_merkle_root(leaves) == expected


def test_merkle_root_rejects_bitcoin_2nd_preimage(tmp_path: Path) -> None:
    """The Bitcoin CVE-2012-2459 attack: [a,b,c] and [a,b,c,c]
    produce the same root under the duplicate-last construction.

    RFC 6962's split-at-largest-pow-2 construction does NOT duplicate
    leaves, so these two trees produce DIFFERENT roots. This is the
    cryptographic property the registry-signing integrity layer
    depends on.
    """
    a = rr.leaf_hash(b"a")
    b = rr.leaf_hash(b"b")
    c = rr.leaf_hash(b"c")
    root_three = rr.build_merkle_root([a, b, c])
    root_three_with_dup = rr.build_merkle_root([a, b, c, c])
    assert root_three != root_three_with_dup


def test_merkle_root_rejects_2nd_preimage_via_compute_registry_root(
    tmp_path: Path,
) -> None:
    """End-to-end: a registry with N rows and a registry where the
    last row is duplicated produce DIFFERENT roots under the
    end-to-end ``compute_registry_root`` path. This locks the
    2nd-preimage attack scenario.
    """
    rows = [
        {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"},
        {"card_id": "b", "fetched_at": "2026-05-02T00:00:00Z"},
        {"card_id": "c", "fetched_at": "2026-05-03T00:00:00Z"},
    ]
    reg_normal = _write_registry(tmp_path / "normal/asset-bytes-registry.jsonl", rows)
    reg_dup = _write_registry(
        tmp_path / "dup/asset-bytes-registry.jsonl", [*rows, rows[-1]]
    )
    root_normal, *_ = rr.compute_registry_root(reg_normal)
    root_dup, *_ = rr.compute_registry_root(reg_dup)
    assert root_normal != root_dup


def test_merkle_root_empty_raises() -> None:
    """Reject empty registry — signing nothing is meaningless and
    almost certainly an operator mistake (typo, wrong path, etc.)."""
    with pytest.raises(ValueError, match="empty"):
        rr.build_merkle_root([])


# --------------------- compute_registry_root + IO ---------------------------


def _write_registry(path: Path, rows: list[dict]) -> Path:
    """Write a JSONL registry file. Caller controls row order — the
    canonical Merkle root is order-dependent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_compute_registry_root_returns_root_count_first_last(tmp_path: Path) -> None:
    rows = [
        {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"},
        {"card_id": "b", "fetched_at": "2026-05-02T00:00:00Z"},
        {"card_id": "c", "fetched_at": "2026-05-03T00:00:00Z"},
    ]
    registry = _write_registry(tmp_path / "asset-bytes-registry.jsonl", rows)
    root, count, first_ts, last_ts = rr.compute_registry_root(registry)
    assert isinstance(root, str)
    assert len(root) == 64
    assert all(c in "0123456789abcdef" for c in root)
    assert count == 3
    assert first_ts == "2026-05-01T00:00:00Z"
    assert last_ts == "2026-05-03T00:00:00Z"


def test_compute_registry_root_is_deterministic(tmp_path: Path) -> None:
    """Two identical-content registries → identical root. This is the
    load-bearing property the signed tag commits to."""
    rows = [{"card_id": "x", "fetched_at": "2026-05-01T00:00:00Z"}]
    reg1 = _write_registry(tmp_path / "a/asset-bytes-registry.jsonl", rows)
    reg2 = _write_registry(tmp_path / "b/asset-bytes-registry.jsonl", rows)
    root1, *_ = rr.compute_registry_root(reg1)
    root2, *_ = rr.compute_registry_root(reg2)
    assert root1 == root2


def test_compute_registry_root_changes_on_row_mutation(tmp_path: Path) -> None:
    """Tampering with a single byte changes the root."""
    base_rows = [
        {"card_id": "a", "byte_sha256": "11" * 32, "fetched_at": "2026-05-01T00:00:00Z"},
    ]
    reg1 = _write_registry(tmp_path / "a/asset-bytes-registry.jsonl", base_rows)
    tampered_rows = [
        {"card_id": "a", "byte_sha256": "22" * 32, "fetched_at": "2026-05-01T00:00:00Z"},
    ]
    reg2 = _write_registry(tmp_path / "b/asset-bytes-registry.jsonl", tampered_rows)
    root1, *_ = rr.compute_registry_root(reg1)
    root2, *_ = rr.compute_registry_root(reg2)
    assert root1 != root2


def test_compute_registry_root_changes_on_row_reorder(tmp_path: Path) -> None:
    """Row order is part of the commitment — re-ordering rows produces
    a different root (Merkle tree order matters)."""
    a = {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}
    b = {"card_id": "b", "fetched_at": "2026-05-02T00:00:00Z"}
    reg_ab = _write_registry(tmp_path / "ab/asset-bytes-registry.jsonl", [a, b])
    reg_ba = _write_registry(tmp_path / "ba/asset-bytes-registry.jsonl", [b, a])
    root_ab, *_ = rr.compute_registry_root(reg_ab)
    root_ba, *_ = rr.compute_registry_root(reg_ba)
    assert root_ab != root_ba


def test_compute_registry_root_skips_blank_lines(tmp_path: Path) -> None:
    """Trailing newline + accidental blank lines must not change the
    root — they're not data, just file-tail noise."""
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = tmp_path / "asset-bytes-registry.jsonl"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(rows[0]) + "\n\n\n")  # extra blanks
    root_with_blanks, *_ = rr.compute_registry_root(registry)
    registry.write_text(json.dumps(rows[0]) + "\n")
    root_clean, *_ = rr.compute_registry_root(registry)
    assert root_with_blanks == root_clean


def test_compute_registry_root_raises_on_corrupt_jsonl(tmp_path: Path) -> None:
    registry = tmp_path / "asset-bytes-registry.jsonl"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text('{"a":1}\n{not-json\n')
    with pytest.raises(ValueError, match="row 2"):
        rr.compute_registry_root(registry)


def test_compute_registry_root_handles_row_without_fetched_at(tmp_path: Path) -> None:
    """``fetched_at`` is in every existing registry row but the
    manifest receipt should tolerate missing timestamps with an
    explicit ``(unknown)`` marker, not crash."""
    rows = [{"card_id": "no-ts"}]
    registry = _write_registry(tmp_path / "asset-bytes-registry.jsonl", rows)
    _, _, first_ts, last_ts = rr.compute_registry_root(registry)
    assert first_ts == "(unknown)"
    assert last_ts == "(unknown)"


def test_compute_registry_root_handles_null_fetched_at(tmp_path: Path) -> None:
    """A row with ``"fetched_at": null`` (JSON null → Python None)
    must surface as ``(unknown)`` rather than the literal string
    ``"None"``. Today no row has a null fetched_at;
    forward-looking infrastructure.
    """
    rows = [{"card_id": "null-ts", "fetched_at": None}]
    registry = _write_registry(tmp_path / "asset-bytes-registry.jsonl", rows)
    _, _, first_ts, last_ts = rr.compute_registry_root(registry)
    assert first_ts == "(unknown)"
    assert last_ts == "(unknown)"


def test_canonicalize_row_rejects_nan_and_infinity() -> None:
    """NaN/Infinity produce non-standard JSON that's not
    cross-platform reproducible. ``allow_nan=False`` makes this
    fail loud at canonicalization time rather than silently producing
    bytes a non-Python verifier can't reproduce.
    """
    import math

    with pytest.raises(ValueError):
        rr.canonicalize_row({"score": math.nan})
    with pytest.raises(ValueError):
        rr.canonicalize_row({"score": math.inf})


def test_read_registry_rows_is_publicly_importable() -> None:
    """Was ``_read_registry_rows`` (underscore = private)
    but ``verify_registry_root`` reaches into it as if it were
    public. Rename to ``read_registry_rows`` so the public contract
    is honest. Tests pin the new name; old name removed so callers
    must update.
    """
    assert hasattr(rr, "read_registry_rows")
    assert not hasattr(rr, "_read_registry_rows")


# --------------------------- write_root_files -------------------------------


def test_write_root_files_emits_root_file_with_trailing_newline(tmp_path: Path) -> None:
    root_path = tmp_path / "registry-root.txt"
    manifest_path = tmp_path / "registry-root-manifest.txt"
    rr.write_root_files(
        root_hex="ab" * 32,
        row_count=3,
        first_ts="2026-05-01T00:00:00Z",
        last_ts="2026-05-03T00:00:00Z",
        root_path=root_path,
        manifest_path=manifest_path,
    )
    assert root_path.read_text() == "ab" * 32 + "\n"


def test_write_root_files_emits_tab_separated_manifest(tmp_path: Path) -> None:
    root_path = tmp_path / "registry-root.txt"
    manifest_path = tmp_path / "registry-root-manifest.txt"
    rr.write_root_files(
        root_hex="ab" * 32,
        row_count=3,
        first_ts="2026-05-01T00:00:00Z",
        last_ts="2026-05-03T00:00:00Z",
        root_path=root_path,
        manifest_path=manifest_path,
    )
    manifest = manifest_path.read_text().rstrip("\n")
    parts = manifest.split("\t")
    assert parts == ["ab" * 32, "3", "2026-05-01T00:00:00Z", "2026-05-03T00:00:00Z"]


def test_main_writes_both_files_in_lockstep(tmp_path: Path) -> None:
    rows = [
        {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"},
        {"card_id": "b", "fetched_at": "2026-05-02T00:00:00Z"},
    ]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    root_path = tmp_path / "data/registry-root.txt"
    manifest_path = tmp_path / "data/registry-root-manifest.txt"
    exit_code = rr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(root_path),
            "--manifest",
            str(manifest_path),
        ]
    )
    assert exit_code == 0
    assert root_path.exists()
    assert manifest_path.exists()
    # Cross-check: re-running compute must return the same root.
    recomputed, *_ = rr.compute_registry_root(registry)
    assert root_path.read_text().strip() == recomputed


def test_main_idempotent_on_repeated_runs(tmp_path: Path) -> None:
    """Same registry → same root file bytes across re-runs. The
    workflow relies on this to detect "operator forgot to refresh"
    vs "operator deliberately changed something".
    """
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    root_path = tmp_path / "data/registry-root.txt"
    manifest_path = tmp_path / "data/registry-root-manifest.txt"
    rr.main(
        ["--registry", str(registry), "--root", str(root_path), "--manifest", str(manifest_path)]
    )
    first_root = root_path.read_text()
    first_manifest = manifest_path.read_text()
    rr.main(
        ["--registry", str(registry), "--root", str(root_path), "--manifest", str(manifest_path)]
    )
    assert root_path.read_text() == first_root
    assert manifest_path.read_text() == first_manifest
