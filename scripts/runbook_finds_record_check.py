"""Runbook rule: the finds step carries the per-candidate overlap record (R7C.38).

The finds step of `ship-tranche.md` must tell the operator to check every
candidate against the existing `/finds` entries and record "new entry" or
"supplements <slug>" before drafting, and must name the overlap gate (R7C.37)
that enforces it at build time.
"""

from __future__ import annotations

import re

LABEL = "finds step lacks the per-candidate new/supplements record or the overlap gate"

_STEP_START = re.compile(r"^\s*\d+\.\s+\*\*Finds\b", re.IGNORECASE)
_NEXT_BLOCK = re.compile(r"^(?:\s*\d+\.\s+\*\*|#)")
_ANY_STEP = re.compile(r"^\s*\d+\.\s+\*\*")
_REQUIRED = (
    re.compile(r"new\s+entry", re.IGNORECASE),
    re.compile(r"supplements", re.IGNORECASE),
    re.compile(r"overlap\s+gate", re.IGNORECASE),
)


def check_finds_record(lines: list[str]) -> list[tuple[int, str, str]]:
    """Flag a finds step missing the record wording or the overlap-gate pointer.

    A numbered step list with no Finds step is flagged too: deleting or
    renaming the step must not make the rule pass by having nothing to check.
    Text with no numbered steps at all is not a step list and is left alone.
    """
    hits: list[tuple[int, str, str]] = []
    found = False
    for i, line in enumerate(lines):
        if not _STEP_START.match(line):
            continue
        found = True
        end = i + 1
        while end < len(lines) and not _NEXT_BLOCK.match(lines[end]):
            end += 1
        block = "\n".join(lines[i:end])
        if not all(r.search(block) for r in _REQUIRED):
            hits.append((i + 1, LABEL, line.strip()))
    if not found and any(_ANY_STEP.match(line) for line in lines):
        hits.append((1, LABEL, "no numbered **Finds** step found"))
    return hits
