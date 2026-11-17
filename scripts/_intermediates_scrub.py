"""Rows of the QC sidecar as the intermediates asset publishes them.

Imported by ``intermediates.py``; kept apart so that script stays under the
per-file function limit.
"""

from __future__ import annotations

import json

# Fields stripped from the QC sidecar rows before packing: bookkeeping that no
# builder reads, so the asset carries only what a rebuild needs.
QC_SIDECAR = "pages_cleaned_qc.jsonl"
QC_DROP_FIELDS = ("cost_estimate_usd",)


def scrub_qc_rows(data: bytes) -> bytes:
    """``data`` with ``QC_DROP_FIELDS`` removed from each JSON row.

    A row without those fields is kept byte-for-byte; a row with them is
    re-serialized in its own key order, which the sidecar writer's
    ``json.dumps`` output round-trips exactly.
    """
    out = []
    for line in data.decode("utf-8").splitlines(keepends=True):
        row = json.loads(line) if line.strip() else None
        if isinstance(row, dict) and any(f in row for f in QC_DROP_FIELDS):
            for field in QC_DROP_FIELDS:
                row.pop(field, None)
            line = json.dumps(row) + ("\n" if line.endswith("\n") else "")
        out.append(line)
    return "".join(out).encode("utf-8")
