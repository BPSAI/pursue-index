#!/usr/bin/env python3
"""Decide whether the web app's production dependency audit passes.

Input is the JSON from ``npm audit --omit=dev --json`` (a path, or ``-`` for
stdin). The allowlist (default ``web/audit-build-only.json``) holds:

``build_only``
    ``{"name@version": reason}``. Exact installed versions of packages whose
    code runs only while the site is built, never in the browser bundle or the
    Worker. A high advisory in one of these does not fail the gate. The match
    is on the version in the lockfile, so a bump to another version of the same
    name is runtime again until someone lists it.

``build_only_roots``
    ``{package: reason}``. The project's own production dependencies that are
    build-only. Every other production dependency is a runtime root. An
    exemption above holds only if no dependency path from a runtime root
    reaches any installed copy of the package (checked on the lockfile graph,
    over dependencies, optional and peer edges).

``accepted_advisories``
    ``{GHSA id: {"reason": ..., "review_by": "YYYY-MM-DD"}}``. A specific advisory that is known and consciously
    left open (for example one that is only fixed in a major release). The
    only way a critical advisory passes.

The gate fails on:
  * any critical advisory that is not individually accepted;
  * any high advisory in a package that is not listed as build-only (so a
    package nobody classified counts as runtime);
  * a severity outside info/low/moderate/high/critical (fail closed);
  * an audit report that is missing, empty, errored or malformed.

Moderate and low findings are reported by npm but do not fail the gate.

Exit status: 0 pass, 1 fail.

Adding a command-line flag: the workflow runs the BASE branch's copy of this
file and always passes it its full arguments (it does not probe ``--help``).
So the rule is: "a new gate flag lands in its own PR first; the workflow
starts passing it in a later PR". A PR that adds a flag and uses it in the
workflow in the same change fails against the base gate.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import sys
from pathlib import Path


def _load_sibling(name: str):
    """Import the helper module that sits next to this file.

    The gate runs as a bare ``python3 -I`` (no script directory on sys.path),
    and the workflow runs a copy of the base commit's gate from a temp
    directory with its helper beside it. Loaded by path, so nothing else in
    that directory can shadow a standard-library import.
    """
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} next to {__file__}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_graph = _load_sibling("_web_audit_graph")
_allow = _load_sibling("_web_audit_allowlist")
_report = _load_sibling("_web_audit_report")
Decision = _report.Decision
KNOWN_SEVERITIES = _report.KNOWN_SEVERITIES
decide_runtime = _report.decide_runtime
unusable_report = _report.unusable_report
read_report = _report.read_report
_review_date = _allow.review_date
load_allowlist_data = _allow.load_allowlist_data
load_allowlist = _allow.load_allowlist
installed_copies = _graph.installed_copies
runtime_roots = _graph.runtime_roots
not_build_only = _graph.not_build_only

# Relative to the working directory: the workflow runs this from the repo root
# with a bare `python3 -I` (no package install), so it must not import the
# project package, and it must not derive a repo root from its own __file__.
# CI passes --allowlist explicitly.
DEFAULT_ALLOWLIST = Path("web") / "audit-build-only.json"
DEFAULT_LOCKFILE = Path("web") / "package-lock.json"


def _ghsa(advisory: dict) -> str:
    url = advisory.get("url")
    if isinstance(url, str) and url:
        return url.rstrip("/").rsplit("/", 1)[-1]
    return str(advisory.get("source", "unknown"))


def _expired_acceptances(accepted: dict, today: datetime.date) -> list[str]:
    """An expired acceptance fails whether or not the advisory is present: it
    is a prompt to re-decide, and a stale line is a liability."""
    out = []
    for ghsa, entry in sorted(accepted.items()):
        try:
            due = _review_date(entry.get("review_by") if isinstance(entry, dict) else None, ghsa)
        except ValueError as exc:
            out.append(f"{ghsa}: {exc}")
            continue
        if today > due:
            out.append(f"{ghsa}: acceptance is past its review_by date {due.isoformat()}")
    return out


def _entry_advisories(name: str, entry: dict, vulns: dict, d: Decision) -> list[dict]:
    """The advisories of one report entry that need a verdict.

    Empty when the entry is harmless or already covered. Fail closed on an
    unknown severity, on the entry or on any advisory under it.
    """
    severity = entry.get("severity")
    if not isinstance(severity, str) or severity not in KNOWN_SEVERITIES:
        d.failures.append(f"{name}: unknown severity {severity!r}")
        return []
    via = entry.get("via") or []
    unknown = [
        a for a in via
        if isinstance(a, dict)
        and (not isinstance(a.get("severity"), str) or a["severity"] not in KNOWN_SEVERITIES)
    ]
    for a in unknown:
        d.failures.append(f"{name}: unknown severity {a.get('severity')!r} on an advisory")
    if unknown or severity not in ("high", "critical"):
        return []
    advisories = [v for v in via if isinstance(v, dict)]
    if advisories:
        return advisories
    # Affected only through another package. Covered by that package's own
    # entry when present; otherwise judge it as a package.
    sources = [v for v in via if isinstance(v, str)]
    if sources and all(s in vulns for s in sources):
        return []
    return [{"name": name, "severity": severity, "url": None}]


def _judge_advisory(adv: dict, name: str, allowlist: dict, lock: dict | None, d: Decision) -> None:
    sev = adv.get("severity")
    pkg = adv.get("name") or name
    ghsa = _ghsa(adv)
    if ghsa in allowlist.get("accepted_advisories", {}):
        _add(d.accepted, ghsa)
    elif sev == "critical":
        d.failures.append(f"{pkg}: critical advisory {ghsa} is not accepted")
    elif sev == "high":
        why = not_build_only(pkg, allowlist, lock)
        if why is None:
            _add(d.build_only, pkg)
        else:
            d.failures.append(
                f"{pkg}: high advisory {ghsa} in a package not classified"
                f" build-only (treated as runtime): {why}"
            )


def _add(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def decide(
    report: object,
    allowlist: dict,
    lock: dict | None = None,
    today: datetime.date | None = None,
) -> Decision:
    d = Decision()
    if isinstance(report, dict) and report.get("error"):
        d.failures.append(f"npm audit reported an error: {report['error']!r}")
        return d
    vulns = report.get("vulnerabilities") if isinstance(report, dict) else None
    if not isinstance(vulns, dict):
        d.failures.append("audit report is malformed (no 'vulnerabilities' object)")
        return d
    d.failures.extend(
        _expired_acceptances(allowlist.get("accepted_advisories", {}), today or datetime.date.today())
    )
    for name, entry in sorted(vulns.items()):
        if not isinstance(entry, dict):
            d.failures.append(f"{name}: malformed entry")
            continue
        for adv in _entry_advisories(name, entry, vulns, d):
            _judge_advisory(adv, name, allowlist, lock, d)
    d.build_only.sort()
    d.accepted.sort()
    return d


def _main_runtime(source: str) -> int:
    try:
        report = read_report(source)
    except (OSError, ValueError) as exc:
        print(f"web-audit gate: REJECT (the audit report is not valid JSON: {exc})")
        return 2
    reason = unusable_report(report)
    if reason:
        print(f"web-audit gate: REJECT (unusable audit report: {reason})")
        return 2
    d = decide_runtime(report)
    for f in d.failures:
        print(f"FAIL {f}")
    print("web-audit gate (runtime): " + ("PASS" if d.ok else "FAIL"))
    return 0 if d.ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audit", help="npm audit --json output file, or - for stdin")
    ap.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    ap.add_argument("--lockfile", type=Path, default=DEFAULT_LOCKFILE)
    ap.add_argument(
        "--runtime",
        action="store_true",
        help="runtime package (the Worker): any high or critical fails, no allowlist",
    )
    args = ap.parse_args(argv)
    if args.runtime:
        return _main_runtime(args.audit)
    try:
        allowlist = load_allowlist(args.allowlist)
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        print(f"web-audit gate: FAIL (cannot read the allowlist: {exc})")
        return 1
    try:
        lock = json.loads(args.lockfile.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"web-audit gate: FAIL (cannot read the lockfile: {exc})")
        return 1
    try:
        report = read_report(args.audit)
    except (OSError, ValueError) as exc:
        print(f"web-audit gate: REJECT (the audit report is not valid JSON: {exc})")
        return 2
    reason = unusable_report(report)
    if reason:
        print(f"web-audit gate: REJECT (unusable audit report: {reason})")
        return 2
    d = decide(report, allowlist, lock)
    if d.build_only:
        print("build-only high advisories (allowed): " + ", ".join(d.build_only))
    if d.accepted:
        print("accepted advisories: " + ", ".join(d.accepted))
    if d.ok:
        print("web-audit gate: PASS")
        return 0
    for f in d.failures:
        print(f"FAIL {f}")
    print("web-audit gate: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
