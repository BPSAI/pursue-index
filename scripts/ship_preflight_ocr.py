#!/usr/bin/env python3
"""Refuse-before-spend OCR preflight for the ship-tranche runbook.

Checked in so the runbook runs a fixed script rather than granting inline
``python -c``. Exits 0 when the operated OCR methodology (engine, concurrency,
key present) is satisfied, 1 otherwise.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

# Code is loaded from where this script lives, never from the data root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pursue_index.release.ship import preflight_ocr


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    result = preflight_ocr(
        engine="llm-dots", concurrency=8,
        anthropic_key_present=bool(env.get("ANTHROPIC_API_KEY")),
    )
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
