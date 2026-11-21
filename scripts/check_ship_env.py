"""Refuse a ``make ship-ready`` run whose environment would test the wrong code.

First step of ``make ship-ready``. Three refusals, all reported before exit 2:

* ``PYTHONPATH`` is set and non-empty. A relative ``src`` leaks into every
  child pytest and picks up the stub packages some tests build.
* ``pursue_index`` imports from somewhere other than this checkout's
  ``src/pursue_index`` (a virtualenv whose editable install points at another
  checkout), so the gates would run another checkout's code.
* ``INTERMEDIATES_LABEL`` is set to something that is not a real ``vX.Y.Z``
  tag (a copied placeholder), or is set without ``PURSUE_DATA_ROOT``.

Usage (run by the Makefile with the interpreter ship-ready will use)::

    python scripts/check_ship_env.py [--root .]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_LABEL_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_PLACEHOLDER = "vX.Y.Z"


def _venv_fix() -> list[str]:
    return [
        "  fix: use a virtualenv installed from THIS checkout, outside the worktree:",
        "    python3 -m venv <dir outside the worktree> && "
        "<dir>/bin/pip install -e '.[dev,llm,embed,r2,og,build-tools]'",
        "    make ship-ready PYTHON=<dir>/bin/python     (with no PYTHONPATH)",
    ]


def check(root: Path, environ: dict[str, str]) -> list[str]:
    problems: list[str] = []

    if environ.get("PYTHONPATH"):
        problems += [
            f"PYTHONPATH is set ({environ['PYTHONPATH']!r}); ship-ready refuses it.",
            "  fix: unset PYTHONPATH and use a worktree virtualenv instead",
            "    (see 'fresh worktree setup' in docs/runbooks/ship-tranche.md).",
        ]

    want = (root / "src" / "pursue_index").resolve()
    try:
        import pursue_index
        got = Path(pursue_index.__file__ or "").resolve().parent
    except ImportError as exc:
        got = None
        problems += [f"cannot import pursue_index with {sys.executable}: {exc}",
                     f"  expected it at {want}", *_venv_fix()]
    if got is not None and got != want:
        problems += [
            f"pursue_index imports from {got}",
            f"  but this checkout's package is {want}",
            f"  interpreter: {sys.executable}",
            *_venv_fix(),
        ]

    label = environ.get("INTERMEDIATES_LABEL", "")
    if label:
        if label == _PLACEHOLDER:
            problems.append(
                f"INTERMEDIATES_LABEL={_PLACEHOLDER} is a placeholder; "
                "set the real tag this release gets, e.g. v1.8.1.")
        elif not _LABEL_RE.match(label):
            problems.append(f"INTERMEDIATES_LABEL={label!r} is not a vX.Y.Z tag such as v1.8.1.")
        if not environ.get("PURSUE_DATA_ROOT"):
            problems.append("INTERMEDIATES_LABEL needs PURSUE_DATA_ROOT, the data root to pack from.")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    problems = check(args.root.resolve(), dict(os.environ))
    if not problems:
        return 0
    print("ship-ready: refusing to start:", file=sys.stderr)
    for line in problems:
        print(line if line.startswith("  ") else f"- {line}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
