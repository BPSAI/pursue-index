#!/usr/bin/env python3
"""Refuse-before-spend OCR preflight for the ship-tranche runbook.

Checked in so the runbook runs a fixed script rather than granting inline
``python -c``. Checks the engine and concurrency the OCR step will use --
``--engine``/``--concurrency`` when given, else the same environment
variables ``pursue ingest run`` resolves (``PURSUE_OCR_ENGINE``,
``PURSUE_OCR_LLM_CONCURRENCY``) -- so a stale environment is refused.
Exits 0 when the operated methodology is satisfied, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

# Code is loaded from where this script lives, never from the data root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pursue_index.release.ship import preflight_ocr


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args(argv)
    raw = env.get("PURSUE_OCR_LLM_CONCURRENCY", "")
    result = preflight_ocr(
        engine=args.engine or env.get("PURSUE_OCR_ENGINE"),
        concurrency=args.concurrency if args.concurrency is not None else (int(raw) if raw.isdigit() else None),
        anthropic_key_present=bool(env.get("ANTHROPIC_API_KEY")),
    )
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
