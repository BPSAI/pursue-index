"""End-to-end real-CLI check for R7C.1 (#168) and R7C.2 (#169).

No deep-stage mocking: ``--dry-run`` guarantees ``download``/``ocr``/``embed``
never run (and, since R7C.2, never promotes or builds either), so a real
``pursue ingest run --tranche <sha> --from-diff --dry-run`` invocation here
exercises the real scoping module (``ingest_scope``) and the real worklist
writer with no filesystem side effect beyond the two worklists. A second
real ``pursue ocr run --worklist`` invocation, against a manifest promoted
by a plain (non-``--from-diff``) real run, exercises the real
tranche-header gate. All of it runs against this repo's own committed
Release-7 artifacts for tranche 096ef2c0058a... (28 new_content PDFs + 1
approved rename with changed bytes = 29), not a synthetic fixture: only
``--manifest``/``--worklist`` are redirected to ``tmp_path`` so the real run
doesn't write into this checkout's own ``data/``.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pursue_index.cli.commands import app
from pursue_index.cli.worklist import read_worklist, worklist_header_tranche

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_096EF_SHA = "096ef2c0058abd412a568d630df31cb836241c1c08c4f67bdc8cdb7e5c8418b9"
_C3F8_SHA = "c3f8209ef5f53a124bf3f30c4a36106ffaa63ea9770ad2d33e2ba5c4fec347c7"


_GATE_ARGS = [
    "--log", str(_REPO_ROOT / "data" / "tranche-approval-log.jsonl"),
    "--snapshots-dir", str(_REPO_ROOT / "data" / "manifests" / "snapshots"),
    "--diff-dir", str(_REPO_ROOT / "data" / "tranche-diffs"),
    "--aliases", str(_REPO_ROOT / "data" / "card-aliases.json"),
    "--asset-registry", str(_REPO_ROOT / "data" / "asset-bytes-registry.jsonl"),
]


def _run_dry_run_ingest(manifest: Path, worklist: Path):
    return runner.invoke(
        app,
        [
            "ingest", "run",
            "--tranche", _096EF_SHA,
            "--from-diff", "--dry-run",
            "--manifest", str(manifest),
            "--worklist", str(worklist),
            *_GATE_ARGS,
        ],
    )


def _run_real_promote(manifest: Path, worklist: Path):
    """Promote-only: no ``--from-diff``, so this writes the real manifest
    without touching download/ocr/embed -- test setup that needs a promoted
    manifest doesn't need deep-stage mocking to get one."""
    return runner.invoke(
        app,
        [
            "ingest", "run",
            "--tranche", _096EF_SHA,
            "--manifest", str(manifest),
            "--worklist", str(worklist),
            *_GATE_ARGS,
        ],
    )


def test_real_dry_run_scopes_29_cards_for_096ef(tmp_path: Path) -> None:
    manifest = tmp_path / "latest.json"
    worklist = tmp_path / "ingest-worklist.txt"

    result = _run_dry_run_ingest(manifest, worklist)

    assert result.exit_code == 0, result.output
    # R7C.2 / #169: --dry-run must promote nothing -- only the worklist(s).
    assert not manifest.exists()
    assert worklist.exists()
    ids = read_worklist(worklist)
    assert len(ids) == 29
    assert worklist_header_tranche(worklist) == _096EF_SHA


def test_real_ocr_run_on_a_stale_worklist_exits_nonzero(tmp_path: Path) -> None:
    """After a real (non-dry) promote-only run, a worklist left over from
    an *older* tranche (c3f8) must make a real ``pursue ocr run``
    invocation refuse -- naming both shas -- rather than silently OCRing
    whatever that stale file names."""
    manifest = tmp_path / "latest.json"
    worklist = tmp_path / "ingest-worklist.txt"
    setup = _run_real_promote(manifest, worklist)
    assert setup.exit_code == 0, setup.output
    assert manifest.exists()

    worklist.write_text(f"# tranche: {_C3F8_SHA}\nsome-stale-card\tnew\n")

    result = runner.invoke(
        app, ["ocr", "run", "--manifest", str(manifest), "--worklist", str(worklist)]
    )

    assert result.exit_code != 0, result.output
    assert _096EF_SHA in result.output
    assert _C3F8_SHA in result.output
