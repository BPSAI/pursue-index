"""Audit-report handling for scripts/web_audit_gate.py.

The verdict type, the report reader and the rules for the Worker (runtime, no
exemptions). Standard library only, loaded by path from beside the gate: the
gate runs as a bare ``python3 -I``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_SEVERITIES = ("info", "low", "moderate", "high", "critical")


@dataclass
class Decision:
    failures: list[str] = field(default_factory=list)
    build_only: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def decide_runtime(report: object) -> Decision:
    """Gate for a package that ships at runtime (the Worker): no exemptions.

    Any high or critical advisory, or a severity outside the known set, fails.
    A transitive-only entry is judged as a vulnerability in its own right.
    """
    d = Decision()
    vulns = report.get("vulnerabilities") if isinstance(report, dict) else None
    if not isinstance(vulns, dict):
        d.failures.append("audit report is malformed (no 'vulnerabilities' object)")
        return d
    for name, entry in sorted(vulns.items()):
        severities = [entry.get("severity") if isinstance(entry, dict) else None]
        if isinstance(entry, dict):
            severities += [v.get("severity") for v in entry.get("via") or [] if isinstance(v, dict)]
        for sev in severities:
            if not isinstance(sev, str) or sev not in KNOWN_SEVERITIES:
                d.failures.append(f"{name}: unknown severity {sev!r}")
            elif sev in ("high", "critical"):
                d.failures.append(f"{name}: {sev} advisory in a runtime dependency (no exemptions)")
    d.failures = sorted(set(d.failures))
    return d


def read_report(source: str) -> object:
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    return json.loads(text)


def unusable_report(report: object) -> str | None:
    """Why ``report`` can't be trusted as an audit result, or None if it can.

    The workflow runs ``npm audit ... || true``, so a network, registry or auth
    failure still leaves a file behind. Such output must never be read as
    "zero findings". Any ``error`` key (whatever its value), a missing
    ``metadata.vulnerabilities`` summary, or a missing ``vulnerabilities``
    object makes the report unusable.
    """
    if not isinstance(report, dict):
        return "the report is not a JSON object"
    if "error" in report:
        return f"npm audit reported an error: {report['error']!r}"
    meta = report.get("metadata")
    if not isinstance(meta, dict) or not isinstance(meta.get("vulnerabilities"), dict):
        return "the report has no metadata.vulnerabilities summary"
    if not isinstance(report.get("vulnerabilities"), dict):
        return "the report has no 'vulnerabilities' object"
    return None
