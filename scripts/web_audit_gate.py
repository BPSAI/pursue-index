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
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Relative to the working directory: the workflow runs this from the repo root
# with a bare `python3 -I` (no package install), so it must not import the
# project package, and it must not derive a repo root from its own __file__.
# CI passes --allowlist explicitly.
KNOWN_SEVERITIES = ("info", "low", "moderate", "high", "critical")
DEFAULT_ALLOWLIST = Path("web") / "audit-build-only.json"
DEFAULT_LOCKFILE = Path("web") / "package-lock.json"


@dataclass
class Decision:
    failures: list[str] = field(default_factory=list)
    build_only: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def _review_date(value: object, where: str) -> datetime.date:
    if not isinstance(value, str):
        raise ValueError(f"{where} needs a review_by date (YYYY-MM-DD)")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{where} review_by must be a YYYY-MM-DD date, got {value!r}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{where} review_by is not a real date: {value!r}") from None


def load_allowlist_data(data: object) -> dict:
    """Validate allowlist content.

    ``build_only`` entries need a non-empty reason. ``accepted_advisories``
    entries are ``{"reason": ..., "review_by": "YYYY-MM-DD"}``; both fields are
    required, so an acceptance can't sit forever without a re-review.
    """
    if not isinstance(data, dict):
        raise ValueError("allowlist must be a JSON object")
    out: dict[str, dict] = {}
    for key in ("build_only", "build_only_roots", "accepted_advisories"):
        section = data.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{key} must map names to reasons")
        for name, entry in section.items():
            if key == "build_only_roots":
                if not isinstance(entry, str) or not entry.strip():
                    raise ValueError(f"{key}[{name!r}] needs a reason")
                continue
            if key == "build_only":
                if not re.fullmatch(r"(@[^/@\s]+/)?[^/@\s]+@[^@\s]+", name):
                    raise ValueError(f"{key}[{name!r}] must be an exact name@version")
                if not isinstance(entry, str) or not entry.strip():
                    raise ValueError(f"{key}[{name!r}] needs a reason")
                continue
            if not isinstance(entry, dict):
                raise ValueError(f"{key}[{name!r}] must be an object with reason and review_by")
            reason = entry.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{key}[{name!r}] needs a reason")
            _review_date(entry.get("review_by"), f"{key}[{name!r}]")
        out[key] = dict(section)
    return out


def load_allowlist(path: Path) -> dict:
    return load_allowlist_data(json.loads(path.read_text(encoding="utf-8")))


def _ghsa(advisory: dict) -> str:
    url = advisory.get("url")
    if isinstance(url, str) and url:
        return url.rstrip("/").rsplit("/", 1)[-1]
    return str(advisory.get("source", "unknown"))


def installed_copies(lock: dict | None, name: str) -> list[tuple[str, str]]:
    """``(lock path, version)`` for every production copy of ``name`` installed."""
    packages = (lock or {}).get("packages")
    if not isinstance(packages, dict):
        return []
    out = []
    for key, meta in packages.items():
        if not isinstance(meta, dict) or meta.get("dev"):
            continue
        if key == f"node_modules/{name}" or key.endswith(f"/node_modules/{name}"):
            out.append((key, str(meta.get("version", ""))))
    return sorted(out)


_EDGE_KINDS = ("dependencies", "optionalDependencies", "peerDependencies")


def _resolve(packages: dict, frm: str, dep: str) -> str | None:
    """The lock path ``dep`` resolves to from ``frm``, the way node looks it up."""
    base = frm
    while True:
        cand = f"{base}/node_modules/{dep}" if base else f"node_modules/{dep}"
        if cand in packages:
            return cand
        if not base:
            return None
        base = base[: base.rfind("node_modules/")].rstrip("/")


def _reachable(packages: dict, start: str) -> set[str]:
    """Lock paths reachable from ``start`` over production, optional and peer edges."""
    seen: set[str] = set()
    todo = [start]
    while todo:
        key = todo.pop()
        meta = packages.get(key)
        if key in seen or not isinstance(meta, dict):
            continue
        seen.add(key)
        for kind in _EDGE_KINDS:
            for dep in meta.get(kind) or {}:
                nxt = _resolve(packages, key, dep)
                if nxt is not None:
                    todo.append(nxt)
    return seen


def runtime_roots(lock: dict | None, build_only_roots: dict) -> list[str]:
    """Production dependencies of the project that are not listed build-only."""
    root = ((lock or {}).get("packages") or {}).get("")
    if not isinstance(root, dict):
        return []
    names = set(root.get("dependencies") or {}) | set(root.get("optionalDependencies") or {})
    return sorted(n for n in names if n not in build_only_roots)


def not_build_only(name: str, allowlist: dict, lock: dict | None) -> str | None:
    """None if ``name`` is build-only: every installed copy is exempted by exact
    version, and no dependency path from a runtime root reaches any copy."""
    build_only = allowlist.get("build_only", {})
    packages = (lock or {}).get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        return "no usable lockfile to verify the dependency paths"
    copies = installed_copies(lock, name)
    if not copies:
        return "no installed copy found in the lockfile"
    unlisted = sorted({f"{name}@{v}" for _, v in copies if f"{name}@{v}" not in build_only})
    if unlisted:
        return "installed " + ", ".join(unlisted) + " is not listed as build-only"
    keys = {k for k, _ in copies}
    for root in runtime_roots(lock, allowlist.get("build_only_roots", {})):
        start = f"node_modules/{root}"
        if start in packages and keys & _reachable(packages, start):
            return f"reachable from the runtime dependency {root}"
    return None


def decide(
    report: object,
    allowlist: dict,
    lock: dict | None = None,
    today: datetime.date | None = None,
) -> Decision:
    d = Decision()
    today = today or datetime.date.today()
    vulns = report.get("vulnerabilities") if isinstance(report, dict) else None
    if isinstance(report, dict) and report.get("error"):
        d.failures.append(f"npm audit reported an error: {report['error']!r}")
        return d
    if not isinstance(vulns, dict):
        d.failures.append("audit report is malformed (no 'vulnerabilities' object)")
        return d

    build_only = allowlist.get("build_only", {})
    accepted = allowlist.get("accepted_advisories", {})
    for ghsa, entry in sorted(accepted.items()):
        # An expired acceptance fails whether or not the advisory is present:
        # it is a prompt to re-decide, and a stale line is a liability.
        try:
            due = _review_date(entry.get("review_by") if isinstance(entry, dict) else None, ghsa)
        except ValueError as exc:
            d.failures.append(f"{ghsa}: {exc}")
            continue
        if today > due:
            d.failures.append(f"{ghsa}: acceptance is past its review_by date {due.isoformat()}")
    seen_build_only: set[str] = set()
    seen_accepted: set[str] = set()

    for name, entry in sorted(vulns.items()):
        if not isinstance(entry, dict):
            d.failures.append(f"{name}: malformed entry")
            continue
        severity = entry.get("severity")
        if not isinstance(severity, str) or severity not in KNOWN_SEVERITIES:
            # Fail closed: a severity npm adds later must not read as harmless.
            d.failures.append(f"{name}: unknown severity {severity!r}")
            continue
        via = entry.get("via") or []
        unknown_adv = [
            a for a in via
            if isinstance(a, dict)
            and (not isinstance(a.get("severity"), str) or a["severity"] not in KNOWN_SEVERITIES)
        ]
        for a in unknown_adv:
            d.failures.append(f"{name}: unknown severity {a.get('severity')!r} on an advisory")
        if unknown_adv:
            continue
        if severity not in ("high", "critical"):
            continue
        advisories = [v for v in via if isinstance(v, dict)]
        if not advisories:
            # Affected only through another package. Covered by that package's
            # own entry when present; otherwise judge it as a package.
            sources = [v for v in via if isinstance(v, str)]
            if sources and all(s in vulns for s in sources):
                continue
            advisories = [{"name": name, "severity": severity, "url": None}]
        for adv in advisories:
            sev = adv.get("severity")
            pkg = adv.get("name") or name
            ghsa = _ghsa(adv)
            if sev == "critical":
                if ghsa in accepted:
                    seen_accepted.add(ghsa)
                else:
                    d.failures.append(f"{pkg}: critical advisory {ghsa} is not accepted")
            elif sev == "high":
                if ghsa in accepted:
                    seen_accepted.add(ghsa)
                else:
                    why = not_build_only(pkg, allowlist, lock)
                    if why is None:
                        seen_build_only.add(pkg)
                    else:
                        d.failures.append(
                            f"{pkg}: high advisory {ghsa} in a package not classified"
                            f" build-only (treated as runtime): {why}"
                        )
    d.build_only = sorted(seen_build_only)
    d.accepted = sorted(seen_accepted)
    return d


def _read(source: str) -> object:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audit", help="npm audit --json output file, or - for stdin")
    ap.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    ap.add_argument("--lockfile", type=Path, default=DEFAULT_LOCKFILE)
    args = ap.parse_args(argv)
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
        report = _read(args.audit)
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
