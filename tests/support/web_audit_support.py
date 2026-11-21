"""Shared builders and paths for the web-audit gate tests."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "web_audit_gate.py"
ALLOWLIST = ROOT / "web" / "audit-build-only.json"
FIXTURES = ROOT / "tests" / "fixtures" / "web_audit"
WEB_LOCK = ROOT / "web" / "package-lock.json"
REAL_LOCK = json.loads(WEB_LOCK.read_text(encoding="utf-8"))
WORKFLOW = ROOT / ".github" / "workflows" / "web-audit.yml"

sys.path.insert(0, str(ROOT / "scripts"))
import web_audit_gate as gate  # noqa: E402,F401  (re-exported to the tests)


def _advisory(name: str, severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict:
    return {
        "source": 1,
        "name": name,
        "dependency": name,
        "title": "t",
        "url": f"https://github.com/advisories/{ghsa}",
        "severity": severity,
        "range": "<1",
    }


def _report(*entries: dict) -> dict:
    counts = {k: 0 for k in ("info", "low", "moderate", "high", "critical")}
    for e in entries:
        counts[e["severity"]] = counts.get(e["severity"], 0) + 1
    counts["total"] = len(entries)
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {e["name"]: e for e in entries},
        "metadata": {"vulnerabilities": counts},
    }


def _vuln(name: str, severity: str, ghsa: str = "GHSA-aaaa-bbbb-cccc") -> dict:
    return {
        "name": name,
        "severity": severity,
        "via": [_advisory(name, severity, ghsa)],
        "effects": [],
        "range": "<1",
        "nodes": [f"node_modules/{name}"],
        "fixAvailable": True,
    }


TODAY = datetime.date(2026, 11, 21)

def _lock(**versions: str) -> dict:
    """A minimal package-lock.json: one top-level install per name."""
    pkgs: dict[str, dict] = {"": {"name": "web", "version": "0.0.1"}}
    for name, version in versions.items():
        pkgs[f"node_modules/{name}"] = {"version": version}
    return {"lockfileVersion": 3, "packages": pkgs}


LOCK = _lock(postcss="8.5.0", preact="10.0.0", astro="7.0.0", somepkg="1.0.0")

def _graph_lock(roots: dict, pkgs: dict) -> dict:
    """A lockfile with a dependency graph.

    ``roots`` maps the project's production dependencies to a version;
    ``pkgs`` maps a lock path (``node_modules/x``) to ``(version, deps)`` where
    ``deps`` is a list of names, or a dict with ``dependencies``,
    ``optionalDependencies`` and ``peerDependencies`` lists.
    """
    packages: dict[str, dict] = {
        "": {"name": "web", "version": "0.0.1", "dependencies": {r: "*" for r in roots}}
    }
    for key, (version, deps) in pkgs.items():
        meta: dict = {"version": version}
        kinds = deps if isinstance(deps, dict) else {"dependencies": deps}
        for kind, names in kinds.items():
            meta[kind] = {n: "*" for n in names}
        packages[key] = meta
    for r, v in roots.items():
        packages.setdefault(f"node_modules/{r}", {"version": v})
    return {"lockfileVersion": 3, "packages": packages}


ROOTS_ALLOW = {
    "build_only": {"postcss@8.5.0": "build time", "nanoid@3.0.0": "build time"},
    "build_only_roots": {"astro": "the site generator runs only at build time"},
    "accepted_advisories": {},
}


def _pc(*extra: tuple[str, tuple]) -> dict:
    """astro (build-only root) -> postcss; plus whatever ``extra`` adds."""
    pkgs = {
        "node_modules/astro": ("7.0.0", ["postcss"]),
        "node_modules/postcss": ("8.5.0", ["nanoid"]),
        "node_modules/nanoid": ("3.0.0", []),
        "node_modules/preact": ("10.0.0", []),
    }
    pkgs.update(dict(extra))
    return _graph_lock({"astro": "7.0.0", "preact": "10.0.0"}, pkgs)


ALLOW = {
    "build_only": {"postcss@8.5.0": "bundled at build time, never shipped"},
    "accepted_advisories": {
        "GHSA-crit-0000-0000": {
            "reason": "image optimisation is unused",
            "review_by": "2099-12-31",
        }
    },
}




def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # YAML 1.1 reads a bare `on:` key as boolean True.
    return data.get("on", data.get(True))
