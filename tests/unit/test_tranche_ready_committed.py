"""Every tranche-ready record committed under ``data/tranche-ready/`` validates.

The poll's producer-side guard refuses an invalid record before it is
written; this is the same check run over what is actually committed, so a
hand edit, a merge mistake or a schema bump that left old records behind
fails here. Each file is also named for its own ``tranche_sha12``. (No
record exists until the first poll after R7C.31 ships; then every one is
checked.)
"""

from __future__ import annotations

import json
from pathlib import Path

from pursue_index.tranche_ready.schema import load_schema, validate

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORD_DIR = REPO_ROOT / "data" / "tranche-ready"


def test_every_committed_record_validates_and_is_named_for_its_sha() -> None:
    schema = load_schema()
    problems = []
    for path in sorted(RECORD_DIR.glob("*")) if RECORD_DIR.is_dir() else []:
        if path.suffix != ".json":
            problems.append(f"{path.name}: not a .json record")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        problems += [f"{path.name}: {e}" for e in validate(record, schema)]
        if path.stem != record.get("tranche_sha12"):
            problems.append(f"{path.name}: named for a different sha")
    assert problems == []
