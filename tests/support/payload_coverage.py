"""Comparison engine for the derived-payload coverage gate.

A derived payload is a file under ``web/public/data/`` that is rebuilt
from the manifest (or from another committed payload) rather than
authored by hand. Each one has an *eligibility predicate*: the set of
entries the current sources say it ought to contain. This module holds
the mechanical part — compare the eligible key set against the shipped
key set and render a diagnosable failure. The predicates themselves are
declared in :mod:`tests.support.payload_specs`.

Everything here is pure: :func:`evaluate` reads its data through a
caller-supplied loader, so the same comparison runs against the working
tree, against a temp dir, or against artifacts extracted from git
history (see ``tests/support/payload_coverage_red_demo.py``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Key = Hashable
Loader = Callable[[str], Any]

#: How many ids a failure message names before it truncates.
FAILURE_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class PayloadSpec:
    """One derived payload and the predicate that decides its contents.

    ``require_no_missing`` / ``require_no_extra`` spell out the direction
    of the assertion, so an exclusion is visible rather than implied:

    * both true  — key-set EQUALITY (shipped == eligible)
    * missing    — coverage only (shipped is a superset of eligible)
    * extra      — structural sanity (shipped is a subset of eligible)
    """

    payload: str
    sources: tuple[str, ...]
    eligible: Callable[[Mapping[str, Any]], set[Key]]
    shipped: Callable[[Any], set[Key]]
    require_no_missing: bool
    require_no_extra: bool
    key_label: str
    rationale: str

    @property
    def id(self) -> str:
        """Short pytest parametrization id."""
        return self.payload


@dataclass(frozen=True)
class CoverageResult:
    """Outcome of comparing one payload against its predicate."""

    spec: PayloadSpec
    eligible_count: int
    shipped_count: int
    missing: list[Key]
    extra: list[Key]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


def json_loader(root: Path) -> Loader:
    """Loader that reads repo-relative paths as JSON under ``root``.

    Caches per loader instance: pages.json is ~16 MB and feeds several
    specs, so a parametrized run would otherwise re-parse it each time.
    """
    cache: dict[str, Any] = {}

    def _load(rel: str) -> Any:
        if rel not in cache:
            cache[rel] = json.loads((root / rel).read_text())
        return cache[rel]

    return _load


def _sorted_keys(keys: set[Key]) -> list[Key]:
    """Deterministic ordering for failure messages."""
    return sorted(keys, key=lambda k: tuple(map(str, k)) if isinstance(k, tuple) else (str(k),))


def evaluate(spec: PayloadSpec, load: Loader) -> CoverageResult:
    """Compare one payload's shipped key set against its eligible set."""
    sources = {rel: load(rel) for rel in spec.sources}
    eligible = spec.eligible(sources)
    shipped = spec.shipped(load(spec.payload))
    missing = _sorted_keys(eligible - shipped) if spec.require_no_missing else []
    extra = _sorted_keys(shipped - eligible) if spec.require_no_extra else []
    return CoverageResult(
        spec=spec,
        eligible_count=len(eligible),
        shipped_count=len(shipped),
        missing=missing,
        extra=extra,
    )


def _format_key(key: Key) -> str:
    if isinstance(key, tuple):
        return ":".join(str(part) for part in key)
    return str(key)


def _format_sample(keys: Sequence[Key], limit: int) -> str:
    shown = ", ".join(_format_key(k) for k in keys[:limit])
    overflow = len(keys) - limit
    return f"{shown} (+{overflow} more)" if overflow > 0 else shown


def describe_failure(result: CoverageResult, limit: int = FAILURE_SAMPLE_LIMIT) -> str:
    """Render a failure an operator can act on without re-deriving it.

    Names the offending ids (bounded) rather than only counting them: an
    undiagnosable red gate is a gate that gets bypassed.
    """
    spec = result.spec
    lines = [
        f"{spec.payload} does not match its eligibility predicate.",
        f"  eligible ({spec.key_label}): {result.eligible_count}    shipped: {result.shipped_count}",
        f"  predicate: {spec.rationale}",
    ]
    if result.missing:
        lines.append(
            f"  MISSING from payload ({len(result.missing)}): "
            f"{_format_sample(result.missing, limit)}"
        )
    if result.extra:
        lines.append(
            f"  STALE in payload, no longer eligible ({len(result.extra)}): "
            f"{_format_sample(result.extra, limit)}"
        )
    lines.append("  Rebuild with `make rebuild-derivatives` and commit the result.")
    return "\n".join(lines)
