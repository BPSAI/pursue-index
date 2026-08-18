"""Tests for ``scripts/verify_registry_root.py``.

The verifier re-derives the Merkle root from the
current registry and compares it to ``data/registry-root.txt``.

* Match: exit 0 with a one-line ``::notice::`` confirming the count
  + short-sha. The workflow uses this exit code.
* Mismatch: exit non-zero. Walk the leaf hashes of the current
  registry against the leaves recoverable from the latest signed
  ``registry-root-*`` git tag (via ``git show <tag>:...``) to surface
  the first divergent row index + row count delta. If no signed tag
  exists yet (bootstrap window before the operator signs the
  baseline), report the root mismatch alone — divergence locator
  needs a prior known-good state.

The signature verify (``git tag -v``) lives in
``.github/workflows/verify-assets-daily.yml`` as a separate step; the
verifier here covers the root-freshness invariant only.
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
import verify_registry_root as vrr  # noqa: E402


def _write_registry(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _write_root_file(path: Path, root_hex: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(root_hex + "\n")
    return path


# --------------------------- happy path -------------------------------------


def test_main_root_matches_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    expected_root, *_ = rr.compute_registry_root(registry)
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", expected_root)
    exit_code = vrr.main(["--registry", str(registry), "--root", str(root_file)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "::notice::" in out
    assert expected_root[:12] in out


# --------------------------- mismatch paths ---------------------------------


def test_main_root_mismatch_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    # Wrong root deliberately.
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", "00" * 32)
    # No --signed-source means the divergence locator gracefully skips.
    exit_code = vrr.main(
        ["--registry", str(registry), "--root", str(root_file), "--signed-source", ""]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "mismatch" in out.lower()
    # The stale recorded root prefix should surface so the operator
    # can grep workflow logs for known-bad roots.
    assert "0000000000000000" in out


def test_main_missing_root_file_exits_nonzero_with_actionable_message(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """The operator forgot to run ``registry_root.py`` after editing
    the registry — surface a clear "refresh the root file" message,
    not a stack trace.
    """
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    exit_code = vrr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(tmp_path / "data/registry-root.txt"),
            "--signed-source",
            "",
        ]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "registry-root.txt" in out
    assert "refresh" in out.lower() or "re-run" in out.lower()


def test_main_corrupt_root_file_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", "not-a-hex-root")
    exit_code = vrr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(root_file),
            "--signed-source",
            "",
        ]
    )
    assert exit_code != 0


# --------------------------- divergence locator -----------------------------


def test_find_first_divergent_index_returns_index_of_first_difference() -> None:
    current = [b"a", b"b", b"c", b"X", b"e"]
    expected = [b"a", b"b", b"c", b"d", b"e"]
    idx = vrr.find_first_divergent_index(current, expected)
    assert idx == 3


def test_find_first_divergent_index_returns_none_when_identical() -> None:
    current = [b"a", b"b", b"c"]
    expected = [b"a", b"b", b"c"]
    assert vrr.find_first_divergent_index(current, expected) is None


def test_find_first_divergent_index_returns_smaller_len_when_truncated() -> None:
    """When current is shorter, the first "divergent index" is the
    point where current ran out — the operator wants to know rows
    were removed."""
    current = [b"a", b"b"]
    expected = [b"a", b"b", b"c"]
    assert vrr.find_first_divergent_index(current, expected) == 2


def test_main_mismatch_reports_divergence_when_signed_source_provided(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """When ``--signed-source`` points at a file that holds the
    last-signed-tag's registry bytes, the verifier walks both leaf
    lists and surfaces the first divergent index + row counts.

    Tests use a file-on-disk substitute rather than shelling out to
    git, so the test runs without a git repo dependency.
    """
    signed_rows = [
        {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"},
        {"card_id": "b", "fetched_at": "2026-05-02T00:00:00Z"},
        {"card_id": "c", "fetched_at": "2026-05-03T00:00:00Z"},
    ]
    current_rows = [
        {"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"},
        {"card_id": "TAMPERED", "fetched_at": "2026-05-02T00:00:00Z"},
        {"card_id": "c", "fetched_at": "2026-05-03T00:00:00Z"},
    ]
    registry = _write_registry(
        tmp_path / "data/asset-bytes-registry.jsonl", current_rows
    )
    signed_source = _write_registry(tmp_path / "signed-registry.jsonl", signed_rows)
    expected_root, *_ = rr.compute_registry_root(signed_source)
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", expected_root)
    exit_code = vrr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(root_file),
            "--signed-source",
            str(signed_source),
        ]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    # Index 1 is the tampered row.
    assert "row 1" in out or "index 1" in out
    assert "3" in out  # the row count


def test_main_missing_registry_exits_nonzero_with_actionable_message(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A missing registry file used to surface as a bare
    Python traceback. Wrap in ``::error::`` with a clear "check path"
    nudge so the operator doesn't have to parse a stack trace.
    """
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", "ab" * 32)
    exit_code = vrr.main(
        [
            "--registry",
            str(tmp_path / "data/no-such-file.jsonl"),
            "--root",
            str(root_file),
            "--signed-source",
            "",
        ]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "::error::" in out
    assert "registry file not found" in out


def test_main_malformed_signed_source_emits_warning_not_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """``git show <tag>:...`` can deliver truncated bytes
    on a network blip. Don't crash with a ValueError stack trace;
    degrade to "skip divergence locator" with a clear warning.
    """
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", "00" * 32)
    # Truncated JSONL — looks like a partial fetch.
    signed = tmp_path / "signed-truncated.jsonl"
    signed.write_text('{"card_id":"trunc')  # mid-string, no closing brace
    exit_code = vrr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(root_file),
            "--signed-source",
            str(signed),
        ]
    )
    # Still exit non-zero because root mismatched, but no crash.
    assert exit_code != 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "malformed" in out.lower()


def test_main_no_signed_tag_skips_divergence_locator_gracefully(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Bootstrap window: signed-source argument is empty (no signed
    tag yet). Verifier still exits non-zero on root mismatch but
    doesn't try to do the leaf-by-leaf walk."""
    rows = [{"card_id": "a", "fetched_at": "2026-05-01T00:00:00Z"}]
    registry = _write_registry(tmp_path / "data/asset-bytes-registry.jsonl", rows)
    root_file = _write_root_file(tmp_path / "data/registry-root.txt", "00" * 32)
    exit_code = vrr.main(
        [
            "--registry",
            str(registry),
            "--root",
            str(root_file),
            "--signed-source",
            "",
        ]
    )
    assert exit_code != 0
    out = capsys.readouterr().out
    # Should NOT crash on the missing signed source. Should explain
    # the limitation so the operator knows to sign the baseline tag.
    assert "no signed" in out.lower() or "baseline" in out.lower()
