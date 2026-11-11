"""Fakes for ``pursue tranche autopilot`` tests: a tmp checkout and a runner.

``FakeRunner`` records every argv. ``git`` runs for real inside the tmp
checkout (local only, no remote); ``pursue``/``make``/``npm`` are simulated
by per-command handlers so no release step ever really runs.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pursue_index.tranche_autopilot.runner import CommandResult

SHA = "ab" * 32
OTHER_SHA = "cd" * 32

Handler = Callable[[Sequence[str], Path], CommandResult]


def receipt(sha: str = SHA, **overrides: object) -> dict:
    """A metadata-only receipt with one allowlisted field edit, then overrides."""
    doc: dict = {
        "tranche_sha256": sha,
        "prior_manifest_sha": OTHER_SHA,
        "summary": {
            "renames_confirmed": 0, "new_content": 0, "quarantined": 0,
            "restored_unchanged": 0, "restored_modified": 0, "restored_unknown": 0,
            "removed": 0, "field_only_changes": 1, "row_changes": 0,
        },
        "renames_confirmed": [], "new_content": [], "quarantined": [],
        "restored_unchanged": [], "restored_modified": [], "restored_unknown": [],
        "removed": [],
        "field_only_changes": [
            {"card_id": "0123456789abcdef",
             "diffs": [{"field": "description", "old": "a", "new": "b"}]},
        ],
        "row_changes": [],
    }
    doc.update(overrides)
    return doc


def with_bucket(doc: dict, bucket: str, rows: list) -> dict:
    doc = json.loads(json.dumps(doc))
    doc[bucket] = rows
    doc["summary"][bucket] = len(rows)
    return doc


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_checkout(tmp_path: Path, doc: dict | None = None, branch: str = "release/t") -> Path:
    repo = tmp_path / "checkout"
    (repo / "data" / "tranche-diffs").mkdir(parents=True)
    (repo / "data" / "manifests").mkdir(parents=True)
    (repo / "web").mkdir()
    if doc is not None:
        path = repo / "data" / "tranche-diffs" / f"tranche-diff-{SHA[:12]}.json"
        path.write_text(json.dumps(doc))
    (repo / "data" / "manifests" / "latest.json").write_text('{"cards": []}\n')
    (repo / "data" / "ingest-worklist.txt").write_text("# tranche: old\n")
    _git(repo, "init", "-q", "-b", branch)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def write_pdf_worklist(repo: Path, sha: str, ids: Sequence[str] = ()) -> None:
    rows = [f"{cid}\tnew" for cid in ids]
    (repo / "data" / "ingest-worklist.txt").write_text(
        "\n".join([f"# tranche: {sha}", "# n card_id(s)", *rows, ""]))


def write_av_worklist(repo: Path, sha12: str, ids: Sequence[str]) -> None:
    (repo / "data" / "ingest-worklist-av.txt").write_text(
        "\n".join([f"# worklist for tranche {sha12} (pursue ingest run --from-diff)", *ids, ""]))


class FakeRunner:
    """Records argv; real git, simulated everything else."""

    def __init__(self, repo: Path, sha: str = SHA) -> None:
        self.repo = repo
        self.sha = sha
        self.calls: list[list[str]] = []
        self.envs: list[Mapping[str, str] | None] = []
        self.handlers: dict[tuple[str, ...], Handler] = {
            ("pursue", "ingest", "check"): lambda a, c: CommandResult(1, "", "NOT approved"),
            ("pursue", "ingest", "approve"): lambda a, c: CommandResult(0, "approved"),
            ("pursue", "storage", "verify"): lambda a, c: CommandResult(0, "ok"),
            ("make", "ship-ready"): lambda a, c: CommandResult(0, "ALL GATES PASSED"),
            ("npm", "run", "test"): lambda a, c: CommandResult(0, "passed"),
        }

    def dry_run(self, argv: Sequence[str], cwd: Path) -> CommandResult:
        write_pdf_worklist(self.repo, self.sha)
        return CommandResult(0, "work-list (0 card_id(s))")

    def promote(self, argv: Sequence[str], cwd: Path) -> CommandResult:
        (self.repo / "data" / "manifests" / "latest.json").write_text('{"cards": [1]}\n')
        return CommandResult(0, "promoted")

    def _handler(self, argv: Sequence[str]) -> Handler:
        if list(argv[:3]) == ["pursue", "ingest", "run"]:
            return self.dry_run if "--dry-run" in argv else self.promote
        for prefix in sorted(self.handlers, key=len, reverse=True):
            if tuple(argv[: len(prefix)]) == prefix:
                return self.handlers[prefix]
        raise AssertionError(f"unexpected command: {argv}")

    def __call__(self, argv: Sequence[str], *, cwd: Path, timeout: float,
                 env: Mapping[str, str] | None = None) -> CommandResult:
        self.calls.append(list(argv))
        self.envs.append(env)
        if argv[0] == "git":
            done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True,
                                  check=False, timeout=timeout)
            return CommandResult(done.returncode, done.stdout, done.stderr)
        return self._handler(argv)(argv, cwd)

    def release_calls(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] != "git"]
