"""The web-audit workflow reports on every pull request.

A ``paths:`` filter on a required check leaves it unreported (and the PR
blocked) when nothing matching changed. So the workflow always runs and
``scripts/web_audit_paths_changed.py`` decides, inside the job, whether the
audit is needed. Same shape as ``scripts/ci_code_paths_changed.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "web_audit_paths_changed.py"
WORKFLOW = ROOT / ".github" / "workflows" / "web-audit.yml"

sys.path.insert(0, str(ROOT / "scripts"))
import web_audit_paths_changed as pc  # noqa: E402


@pytest.mark.parametrize(
    "path",
    [
        "web/package.json",
        "web/package-lock.json",
        "web/audit-build-only.json",
        "web/src/pages/index.astro",
        "worker/package-lock.json",
        "worker/index.js",
        "scripts/web_audit_gate.py",
        "scripts/web_audit_paths_changed.py",
        ".github/workflows/web-audit.yml",
        ".node-version",
        ".npmrc",
        "web/.npmrc",
        "worker/.npmrc",
        "web/.nvmrc",
    ],
)
def test_audited_paths_need_the_audit(path):
    assert pc.needs_audit(path)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "docs/runbooks/ship-tranche.md",
        "data/registry-root.txt",
        "src/pursue_index/ingest_scope.py",
        "tests/unit/test_web_audit_gate.py",
        ".github/workflows/tests.yml",
        "website/index.html",
        "workers/x.js",
    ],
)
def test_other_paths_do_not(path):
    assert not pc.needs_audit(path)


def test_a_quoted_path_fails_safe():
    assert pc.needs_audit('"docs/caf\\303\\251.md"')


def _run(data: bytes) -> str:
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input=data, capture_output=True, check=True
    )
    return r.stdout.decode().strip()


def test_cli_false_only_when_nothing_audited_changed():
    assert _run(b"docs/a.md\0data/x.json\0") == "false"
    assert _run(b"docs/a.md\0web/package.json\0") == "true"
    assert _run(b"docs/a.md\ndata/x.json\n") == "false"


def test_cli_empty_input_fails_safe_to_true():
    assert _run(b"") == "true"


def test_cli_undecodable_name_does_not_crash():
    assert _run(b"docs/\xff.md\0") in ("true", "false")


# --- workflow shape: no paths filter, decided inside the job -------------


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    return data.get("on", data.get(True))


def test_pull_request_trigger_has_no_paths_filter():
    pr = _on(_wf())["pull_request"]
    assert not pr or "paths" not in pr
    assert not pr or "paths-ignore" not in pr


def test_the_job_decides_with_the_base_refs_classifier():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'git show "$BASE_SHA:scripts/web_audit_paths_changed.py"' in text
    assert "$RUNNER_TEMP" in text


def test_every_step_after_the_decision_is_conditional():
    steps = _wf()["jobs"]["audit"]["steps"]
    names = [s.get("id") for s in steps]
    i = names.index("changes")
    for st in steps[i + 1 :]:
        cond = st.get("if", "")
        assert "steps.changes.outputs.audit" in cond, st


def test_an_unchanged_pr_prints_a_visible_notice():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "::notice" in text
    steps = _wf()["jobs"]["audit"]["steps"]
    skip = [s for s in steps if "!= 'true'" in s.get("if", "")]
    assert skip and "::notice" in skip[0]["run"]


def test_scheduled_and_dispatch_runs_always_audit():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'audit=true' in text
    assert "github.event_name" in text


@pytest.mark.parametrize(
    "path",
    [
        "scripts/_web_audit_allowlist.py",
        "scripts/_web_audit_graph.py",
        "scripts/_web_audit_report.py",
        "scripts/_web_audit_future_helper.py",
    ],
)
def test_gate_helper_modules_need_the_audit(path):
    """The gate loads its helpers from beside itself, so editing one changes
    the gate's decision and must run the audit."""
    assert pc.needs_audit(path)


def test_every_helper_on_disk_is_covered():
    helpers = sorted(p for p in (ROOT / "scripts").glob("_web_audit_*.py"))
    assert helpers, "expected gate helper modules"
    for p in helpers:
        assert pc.needs_audit(f"scripts/{p.name}"), p.name


# --- the workflow and the classifier agree on what a helper is ------------

HELPER_NAMES = [
    "scripts/_web_audit_graph.py",
    "scripts/_web_audit_allowlist.py",
    "scripts/_web_audit_v2.py",
    "scripts/_web_audit_2.py",
    "scripts/_web_audit_Upper.py",
    "scripts/_web_audit_.py",
    "scripts/_web_audit_x.txt",
    "scripts/_web_audit_x-y.py",
    "scripts/sub/_web_audit_x.py",
    "scripts/web_audit_x.py",
]


def _workflow_helper_regex() -> str:
    import re

    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"grep -E '([^']*_web_audit_[^']*)'", text)
    assert m, "the helper copy loop's grep pattern is missing"
    return m.group(1)


def test_the_classifier_audits_a_superset_of_what_the_workflow_copies():
    import re

    pattern = re.compile(_workflow_helper_regex())
    for name in HELPER_NAMES:
        # Anything the workflow would copy from the base must be audited; the
        # classifier may audit more (the broad rule), never less.
        if pattern.search(name):
            assert pc.needs_audit(name), name
    assert pc.is_helper("scripts/_web_audit_v2.py")
    assert pc.needs_audit("scripts/_web_audit_Upper.py")
    assert pc.needs_audit("scripts/_web_audit_x-y.py")
