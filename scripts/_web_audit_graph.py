"""Lockfile helpers for scripts/web_audit_gate.py.

Kept apart from the gate so each file stays small. Standard library only: the
gate runs as a bare ``python3 -I`` with no package installed, and the workflow
copies this file next to the base commit's gate.

All functions take the parsed ``package-lock.json`` (``lock``) and work on its
``packages`` map, keyed by lock path (``node_modules/a/node_modules/b``).
"""

from __future__ import annotations

_EDGE_KINDS = ("dependencies", "optionalDependencies", "peerDependencies")


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


def reachable(packages: dict, start: str) -> set[str]:
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


def usable_lock(lock: dict | None) -> bool:
    """True if ``lock`` has a packages map with a root entry to walk from."""
    packages = (lock or {}).get("packages")
    return isinstance(packages, dict) and isinstance(packages.get(""), dict)


def not_build_only(name: str, allowlist: dict, lock: dict | None) -> str | None:
    """None if ``name`` is build-only: every installed copy is exempted (by exact
    version, or by bare name in a legacy allowlist), and no dependency path
    from a runtime root reaches any copy."""
    build_only = allowlist.get("build_only", {})
    if not usable_lock(lock):
        return "no usable lockfile to verify the dependency paths"
    packages = lock["packages"]
    copies = installed_copies(lock, name)
    if not copies:
        return "no installed copy found in the lockfile"
    unlisted = sorted(
        {f"{name}@{v}" for _, v in copies if f"{name}@{v}" not in build_only and name not in build_only}
    )
    if unlisted:
        return "installed " + ", ".join(unlisted) + " is not listed as build-only"
    keys = {k for k, _ in copies}
    for root in runtime_roots(lock, allowlist.get("build_only_roots", {})):
        start = f"node_modules/{root}"
        if start in packages and keys & reachable(packages, start):
            return f"reachable from the runtime dependency {root}"
    return None
