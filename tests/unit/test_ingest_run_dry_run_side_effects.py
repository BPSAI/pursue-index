"""Acceptance tests for R7C.2 / #169.

``ingest run --tranche <sha> --from-diff --dry-run`` used to promote
``data/manifests/latest.json`` + its deploy-side mirrors and run the
poster/thumb builders -- all *before* ``execute_from_diff`` even looked at
``--dry-run``. These tests pin the fix:

  1. A dry run inside a real git repo touches nothing on disk except the
     two worklist files -- `git status --porcelain` proves it directly,
     rather than trusting an allowlist of paths this test might miss.
  2. The dry run's printed scope/counts match a real run's, so an operator
     can trust what they see before anything spends or promotes.
  3. A real run whose poster builder fails exits non-zero, names the
     builder, and still leaves the manifest promoted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pursue_index.cli.commands import app

runner = CliRunner()

_SHA = "a1b2c3d4e5f6" + "0" * 52  # 64 hex chars


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo_root, check=True)


def _new_content_rows() -> list[dict]:
    return [
        {"new_card_id": "00000000000000a1", "title": "X", "asset_url": "https://x/a.pdf"},
        {"new_card_id": "00000000000000a2", "title": "Y", "asset_url": "https://x/b.pdf"},
    ]


def _build_fixture_repo(tmp_path: Path) -> Path:
    """A git-tracked fixture repo with the approval gate, a snapshot, and a
    tranche-diff for ``_SHA``, plus the deploy-side surfaces a real
    (non-dry) run would mirror into -- so the git-status assertion for the
    dry run is meaningful (those surfaces exist and are tracked, but must
    stay untouched)."""
    repo_root = tmp_path / "repo"

    manifests_dir = repo_root / "data" / "manifests"
    snapshots_dir = manifests_dir / "snapshots"
    snapshots_dir.mkdir(parents=True)
    (manifests_dir / "latest.json").write_text(
        json.dumps({"csv_sha256": "priorsha", "cards": []}), encoding="utf-8"
    )
    (snapshots_dir / f"{_SHA}.json").write_text(
        json.dumps({"csv_sha256": _SHA, "fetched_at": "2026-10-24T00:00:00Z", "cards": []}),
        encoding="utf-8",
    )

    diff_dir = repo_root / "data" / "tranche-diffs"
    diff_dir.mkdir(parents=True)
    (diff_dir / f"tranche-diff-{_SHA[:12]}.json").write_text(
        json.dumps({
            "tranche_sha256": _SHA,
            "summary": {"new_content": 2},
            "renames_confirmed": [],
            "new_content": _new_content_rows(),
            "quarantined": [],
            "restored_unchanged": [],
            "restored_modified": [],
            "field_only_changes": [],
        }),
        encoding="utf-8",
    )

    (repo_root / "data" / "tranche-approval-log.jsonl").write_text(
        json.dumps({"tranche_sha256": _SHA}) + "\n", encoding="utf-8"
    )
    (repo_root / "data" / "card-aliases.json").write_text(
        json.dumps({"aliases": []}), encoding="utf-8"
    )
    (repo_root / "data" / "asset-bytes-registry.jsonl").write_text("", encoding="utf-8")

    web_build = repo_root / "web" / "src" / "data"
    web_build.mkdir(parents=True)
    (web_build / "manifest.json").write_text(
        json.dumps({"csv_sha256": "priorsha", "cards": []}), encoding="utf-8"
    )
    web_snapshots = repo_root / "web" / "public" / "data" / "snapshots"
    web_snapshots.mkdir(parents=True)
    (web_snapshots / "index.json").write_text("[]", encoding="utf-8")

    _init_git_repo(repo_root)
    return repo_root


def _run_args(repo_root: Path, *, dry_run: bool) -> list[str]:
    args = [
        "ingest", "run",
        "--tranche", _SHA,
        "--from-diff",
        "--manifest", str(repo_root / "data" / "manifests" / "latest.json"),
        "--worklist", str(repo_root / "data" / "ingest-worklist.txt"),
        "--log", str(repo_root / "data" / "tranche-approval-log.jsonl"),
        "--snapshots-dir", str(repo_root / "data" / "manifests" / "snapshots"),
        "--diff-dir", str(repo_root / "data" / "tranche-diffs"),
        "--aliases", str(repo_root / "data" / "card-aliases.json"),
        "--asset-registry", str(repo_root / "data" / "asset-bytes-registry.jsonl"),
    ]
    if dry_run:
        args.append("--dry-run")
    return args


def _git_status_porcelain(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_root, check=True,
        capture_output=True, text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_dry_run_touches_only_the_two_worklists(tmp_path: Path) -> None:
    repo_root = _build_fixture_repo(tmp_path)

    result = runner.invoke(app, _run_args(repo_root, dry_run=True))
    assert result.exit_code == 0, result.output

    status = _git_status_porcelain(repo_root)
    touched = {line.split(maxsplit=1)[1] for line in status}
    assert touched == {"data/ingest-worklist.txt"}, (
        f"dry run touched more than the worklist: {status}"
    )


def test_dry_run_and_real_run_print_the_same_scope(tmp_path: Path) -> None:
    dry_repo = _build_fixture_repo(tmp_path / "dry")
    real_repo = _build_fixture_repo(tmp_path / "real")

    dry_result = runner.invoke(app, _run_args(dry_repo, dry_run=True))
    assert dry_result.exit_code == 0, dry_result.output

    # The real run would try to exercise download/ocr/embed for the
    # scoped cards; refuse-before-spend (preflight_ocr, no ANTHROPIC key
    # here) stops it right after the scope is printed, which is exactly
    # the output being compared.
    real_result = runner.invoke(app, _run_args(real_repo, dry_run=False))

    def _scope_lines(output: str) -> list[str]:
        lines = output.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith("work-list ("))
        return lines[start:start + 3]

    assert _scope_lines(dry_result.output) == _scope_lines(real_result.output)


def test_real_run_builder_failure_exits_nonzero_names_builder_keeps_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = _build_fixture_repo(tmp_path)
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "build_video_posters.py").write_text("#!/usr/bin/env python\n")
    (scripts_dir / "build_pdf_thumbs.py").write_text("#!/usr/bin/env python\n")
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "scripts"], cwd=repo_root, check=True)

    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):
        if "build_video_posters.py" in " ".join(cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="r2 mirror missing")
        if any("build_pdf_thumbs.py" in part for part in cmd):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # No --from-diff: exercises promote_and_report directly without also
    # needing to mock the download/ocr/embed stages.
    result = runner.invoke(
        app,
        [
            "ingest", "run",
            "--tranche", _SHA,
            "--manifest", str(repo_root / "data" / "manifests" / "latest.json"),
            "--log", str(repo_root / "data" / "tranche-approval-log.jsonl"),
            "--snapshots-dir", str(repo_root / "data" / "manifests" / "snapshots"),
            "--diff-dir", str(repo_root / "data" / "tranche-diffs"),
        ],
    )

    assert result.exit_code != 0, result.output
    assert "build_video_posters.py" in result.output
    manifest = repo_root / "data" / "manifests" / "latest.json"
    assert json.loads(manifest.read_text())["csv_sha256"] == _SHA
