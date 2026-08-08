"""Run the derived-payload coverage gate against a historical revision.

Evidence harness for the gate in
``tests/integration/test_derived_payload_coverage.py``: it materializes
each spec's payload *and* sources as they existed at a given revision,
then runs the same predicates over that tree. This answers the question
a new gate always has to answer — "would it have caught the drift that
motivated it?" — against real history rather than a synthetic fixture.

Usage::

    python -m tests.support.payload_coverage_red_demo f3ba027^   # RED
    python -m tests.support.payload_coverage_red_demo HEAD       # PASS

Not collected by pytest (no ``test_`` prefix) and not part of CI: it
shells out to ``git show``, which needs full history a shallow CI
checkout may not have. The captured output is quoted in the gate
module's docstring.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from tests.support.payload_coverage import describe_failure, evaluate, json_loader
from tests.support.payload_specs import SPECS

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _paths_for_specs() -> list[str]:
    """Every repo-relative file the declared specs read, deduplicated."""
    seen: list[str] = []
    for spec in SPECS:
        for rel in (*spec.sources, spec.payload):
            if rel not in seen:
                seen.append(rel)
    return seen


def _extract_tree(rev: str, dest: Path) -> None:
    """Copy each spec input out of ``rev`` into ``dest`` at the same path."""
    for rel in _paths_for_specs():
        blob = subprocess.run(
            ["git", "show", f"{rev}:{rel}"],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)


def run_demo(rev: str) -> int:
    """Evaluate every spec against ``rev``; return the failure count."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _extract_tree(rev, root)
        load = json_loader(root)
        failures = 0
        for spec in SPECS:
            result = evaluate(spec, load)
            if result.ok:
                print(f"ok   {spec.payload}: {result.shipped_count} entries")
                continue
            failures += 1
            print(describe_failure(result))
            print()
    verdict = "RED" if failures else "PASS"
    print(f"{verdict}: {failures} of {len(SPECS)} payloads fail against {rev}")
    return failures


def main(argv: list[str]) -> int:
    rev = argv[1] if len(argv) > 1 else "HEAD"
    return 1 if run_demo(rev) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
