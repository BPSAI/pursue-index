"""The web-audit workflow: shape, and which gate and allowlist a PR runs.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.support.web_audit_support import (
    SCRIPT,
    WORKFLOW,
    _on,
    _wf,
)

# --- workflow shape -------------------------------------------------------


def test_workflow_runs_on_every_pr_and_weekly():
    on = _on(_wf())
    assert "pull_request" in on
    # No paths filter: see tests/unit/test_web_audit_paths_changed.py.
    assert not on["pull_request"] or "paths" not in on["pull_request"]
    crons = [s["cron"] for s in on["schedule"]]
    assert crons and all(len(c.split()) == 5 for c in crons)
    assert "workflow_dispatch" in on


def test_workflow_is_read_only_and_secretless():
    text = WORKFLOW.read_text(encoding="utf-8")
    data = _wf()
    assert data["permissions"] == {"contents": "read"}
    assert "${{ secrets" not in text
    assert "persist-credentials: false" in text


def test_workflow_check_name_is_stable():
    data = _wf()
    assert data["name"] == "web-audit"
    assert list(data["jobs"]) == ["audit"]
    assert data["jobs"]["audit"]["name"] == "web-audit"


def test_workflow_runs_the_gate_on_npm_audit_json():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "npm audit --omit=dev --json" in text
    assert "web_audit_gate.py" in text



# --- the PR runs the BASE ref's gate and allowlist ------------------------
#
# A PR that edits scripts/web_audit_gate.py or web/audit-build-only.json must
# not be judged by its own edits, so the workflow reads both from the base
# commit, the way tests.yml reads its classifier. These tests run the
# workflow's own "inputs" step in a throwaway git repository.


GATE_PATH = "scripts/web_audit_gate.py"
ALLOW_PATH = "web/audit-build-only.json"


def _inputs_step() -> dict:
    steps = _wf()["jobs"]["audit"]["steps"]
    found = [s for s in steps if s.get("id") == "inputs"]
    assert found, "the workflow needs a step with id 'inputs'"
    return found[0]


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8")


def _run_inputs(event: str, base_files: dict, head_files: dict, base_sha: str | None = None):
    step = _inputs_step()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        runner_temp = Path(tmp) / "rt"
        repo.mkdir()
        runner_temp.mkdir()
        _git(repo, "init", "-q")
        _write(repo, "README", "x")
        for rel, text in base_files.items():
            _write(repo, rel, text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        sha = _git(repo, "rev-parse", "HEAD")
        for rel, text in head_files.items():
            _write(repo, rel, text)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "head")
        out = Path(tmp) / "out"
        out.write_text("")
        env = {
            **os.environ,
            "EVENT": event,
            "BASE_SHA": base_sha or sha,
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(out),
        }
        r = subprocess.run(
            ["bash", "-e", "-c", step["run"]], cwd=repo, env=env, capture_output=True, text=True
        )
        outputs = dict(
            line.split("=", 1) for line in out.read_text().splitlines() if "=" in line
        )
        copied = {str(p): p.read_text() for p in runner_temp.iterdir()}
        return r, outputs, copied, runner_temp


def test_pr_uses_the_base_copies_not_the_prs_own():
    r, out, copied, rt = _run_inputs(
        "pull_request",
        {GATE_PATH: "BASE GATE", ALLOW_PATH: '{"base": 1}'},
        {GATE_PATH: "PR GATE (weakened)", ALLOW_PATH: '{"pr": 1}'},
    )
    assert r.returncode == 0, r.stderr
    assert out["gate"].startswith(str(rt)) and out["allowlist"].startswith(str(rt))
    assert copied[out["gate"]] == "BASE GATE"
    assert copied[out["allowlist"]] == '{"base": 1}'


def test_pr_falls_back_to_its_own_copies_on_first_introduction_only():
    r, out, _, _ = _run_inputs("pull_request", {}, {GATE_PATH: "G", ALLOW_PATH: "{}"})
    assert r.returncode == 0, r.stderr
    assert out["gate"] == GATE_PATH and out["allowlist"] == ALLOW_PATH
    assert "first introduction" in (r.stdout + r.stderr)


@pytest.mark.parametrize("present", [GATE_PATH, ALLOW_PATH])
def test_pr_fails_when_only_one_of_the_two_exists_at_the_base(present):
    r, out, _, _ = _run_inputs(
        "pull_request", {present: "x"}, {GATE_PATH: "G", ALLOW_PATH: "{}"}
    )
    assert r.returncode != 0
    assert "gate" not in out


def test_pr_fails_when_the_base_commit_is_unreadable():
    r, out, _, _ = _run_inputs(
        "pull_request", {GATE_PATH: "G", ALLOW_PATH: "{}"}, {}, base_sha="0" * 40
    )
    assert r.returncode != 0


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_non_pr_events_use_the_checked_out_copies(event):
    r, out, copied, _ = _run_inputs(
        event, {GATE_PATH: "BASE", ALLOW_PATH: "{}"}, {GATE_PATH: "HEAD"}
    )
    assert r.returncode == 0, r.stderr
    assert out["gate"] == GATE_PATH and out["allowlist"] == ALLOW_PATH
    assert copied == {}


def test_the_gate_steps_take_the_selected_paths_through_env():
    steps = _wf()["jobs"]["audit"]["steps"]
    gates = [s for s in steps if s.get("name", "").startswith("Gate")]
    assert len(gates) == 2
    web, worker = gates
    assert web["env"]["GATE"] == "${{ steps.inputs.outputs.gate }}"
    assert web["env"]["ALLOWLIST"] == "${{ steps.inputs.outputs.allowlist }}"
    assert '"$GATE"' in web["run"] and '"$ALLOWLIST"' in web["run"]
    assert "--lockfile web/package-lock.json" in web["run"]
    # The Worker run also uses the selected gate, never the PR's own file.
    assert worker["env"]["GATE"] == "${{ steps.inputs.outputs.gate }}"
    assert "scripts/web_audit_gate.py" not in worker["run"]
    assert "${{" not in web["run"] and "${{" not in worker["run"]




def test_pr_copies_the_bases_helper_beside_the_bases_gate():
    graph, allow = "scripts/_web_audit_graph.py", "scripts/_web_audit_allowlist.py"
    r, out, copied, rt = _run_inputs(
        "pull_request",
        {GATE_PATH: "BASE GATE", ALLOW_PATH: "{}", graph: "BASE GRAPH", allow: "BASE ALLOW",
         "scripts/other.py": "unrelated"},
        {GATE_PATH: "PR GATE", ALLOW_PATH: "{}", graph: "PR GRAPH (weakened)", allow: "PR ALLOW"},
    )
    assert r.returncode == 0, r.stderr
    assert copied[str(rt / "_web_audit_graph.py")] == "BASE GRAPH"
    assert copied[str(rt / "_web_audit_allowlist.py")] == "BASE ALLOW"
    assert str(rt / "other.py") not in copied
    assert Path(out["gate"]).parent == rt


def test_pr_without_a_base_helper_copies_none():
    r, out, copied, rt = _run_inputs(
        "pull_request",
        {GATE_PATH: "BASE GATE", ALLOW_PATH: "{}"},
        {GATE_PATH: "PR GATE", ALLOW_PATH: "{}", "scripts/_web_audit_graph.py": "PR HELPER"},
    )
    assert r.returncode == 0, r.stderr
    assert str(rt / "_web_audit_graph.py") not in copied
    assert str(rt / "_web_audit_allowlist.py") not in copied


# --- the registry is pinned; no --help probe ------------------------------


def _run_texts() -> list[str]:
    return [st["run"] for st in _wf()["jobs"]["audit"]["steps"] if "run" in st]


def test_every_npm_audit_pins_the_registry():
    audits = [line for t in _run_texts() for line in t.splitlines() if "npm audit" in line]
    assert len(audits) == 2, audits
    for line in audits:
        assert "--registry=https://registry.npmjs.org/" in line, line


# --- each audit runs from a clean directory with empty npm configs --------
#
# --registry alone does not stop a PR-supplied .npmrc from steering the audit
# (proxy, https-proxy, strict-ssl, cafile, a scoped registry). So each audit
# runs in a fresh temporary directory holding only the package's manifest and
# lockfile, with empty user and global configs.

AUDIT_STEPS = [
    ("npm audit (production dependencies)", "web", "audit.json"),
    ("npm audit (Worker production dependencies)", "worker", "worker-audit.json"),
]


def _audit_step(name: str) -> dict:
    found = [s for s in _wf()["jobs"]["audit"]["steps"] if s.get("name") == name]
    assert found, name
    return found[0]


@pytest.mark.parametrize(("name", "pkg", "out"), AUDIT_STEPS)
def test_each_audit_runs_in_a_clean_directory_with_empty_configs(name, pkg, out):
    step = _audit_step(name)
    run = step["run"]
    assert "working-directory" not in step
    assert "mktemp -d" in run
    assert f"{pkg}/package.json" in run and f"{pkg}/package-lock.json" in run
    assert "--registry=https://registry.npmjs.org/" in run
    assert "--userconfig=" in run and "--globalconfig=" in run
    assert "--omit=dev --json" in run


@pytest.mark.parametrize(("name", "pkg", "out"), AUDIT_STEPS)
def test_each_audit_ignores_a_hostile_npmrc_in_the_package(name, pkg, out):
    step = _audit_step(name)
    with tempfile.TemporaryDirectory() as tmp:
        repo, rt, bindir = Path(tmp) / "repo", Path(tmp) / "rt", Path(tmp) / "bin"
        for d in (repo / pkg, rt, bindir):
            d.mkdir(parents=True)
        (repo / pkg / "package.json").write_text("{}", encoding="utf-8")
        (repo / pkg / "package-lock.json").write_text("{}", encoding="utf-8")
        (repo / pkg / ".npmrc").write_text("https-proxy=http://evil.invalid\n", encoding="utf-8")
        (repo / ".npmrc").write_text("strict-ssl=false\n", encoding="utf-8")
        fake = bindir / "npm"
        fake.write_text(
            "#!/bin/bash\n"
            'echo "CWD=$PWD"\n'
            'echo "LS=$(ls -A | LC_ALL=C sort | tr \'\\n\' \',\')"\n'
            'for a in "$@"; do echo "ARG=$a"; case "$a" in'
            ' --userconfig=*|--globalconfig=*) f=${a#*=};'
            ' echo "SIZE=$(wc -c < "$f")";; esac; done\n',
            encoding="utf-8",
        )
        fake.chmod(0o755)
        env = {**os.environ, "RUNNER_TEMP": str(rt), "PATH": f"{bindir}:{os.environ['PATH']}"}
        r = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
            cwd=repo, env=env, capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        lines = (rt / out).read_text(encoding="utf-8").splitlines()
        cwd = next(x for x in lines if x.startswith("CWD="))[4:]
        assert cwd.startswith(str(rt)) and Path(cwd) != repo / pkg
        assert "LS=package-lock.json,package.json," in lines
        args = [x[4:] for x in lines if x.startswith("ARG=")]
        assert "--registry=https://registry.npmjs.org/" in args
        user = next(a for a in args if a.startswith("--userconfig="))
        glob = next(a for a in args if a.startswith("--globalconfig="))
        assert lines.count("SIZE=0") == 2, lines
        # npm refuses to load one file as both the user and global config.
        assert user.split("=", 1)[1] != glob.split("=", 1)[1]
        assert not Path(user.split("=", 1)[1]).is_relative_to(cwd)
        assert not Path(glob.split("=", 1)[1]).is_relative_to(cwd)


def test_the_gate_flag_rule_is_documented():
    text = WORKFLOW.read_text(encoding="utf-8")
    rule = "a new gate flag lands in its own PR first"
    assert rule in text
    assert rule in SCRIPT.read_text(encoding="utf-8")


def test_the_gate_steps_pass_full_arguments_and_do_not_probe_help():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--help" not in text
    steps = {s.get("name"): s for s in _wf()["jobs"]["audit"]["steps"]}
    assert "--lockfile web/package-lock.json" in steps["Gate"]["run"]
    assert "--runtime" in steps["Gate (Worker, runtime)"]["run"]
    assert "predates" not in text
