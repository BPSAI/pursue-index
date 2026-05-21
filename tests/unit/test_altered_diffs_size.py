"""Size gate on ``web/src/data/altered-diffs.json`` (Sprint 4i #7).

The diff payload is SSR-imported into ``/altered/[card_id].astro`` so
every byte gets parsed at build time. The current ~9.5 MB payload is
fine; if a future tranche triples the corpus, the Astro build could
OOM. This gate fires early — at ~2x growth — so the operator gets a
deterministic alert before the build breaks rather than a wall of red
in a deploy.

When this fires, the documented mitigation (Sprint 4i #6 in
state.md, also flagged on PR #72) is to switch to keyed-per-card
JSON: one file per card under ``web/src/data/altered-diffs/<card_id>.json``,
imported lazily from the page.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALTERED_DIFFS = REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"

# 20 MB threshold — current payload is 9.5 MB (~50% headroom before a
# growth-event trips this). Triple the current corpus would hit ~28 MB
# and OOM the Astro build per laverna P3; this gate catches a doubling
# while there's still time to keyed-per-card-split before deploy.
MAX_BYTES = 20 * 1024 * 1024


def test_altered_diffs_file_exists() -> None:
    """The file is build-time SSR-imported; absence breaks /altered/*."""
    assert ALTERED_DIFFS.exists(), (
        f"missing {ALTERED_DIFFS.relative_to(REPO_ROOT)}; rebuild via "
        "`python scripts/build_altered_diffs.py`"
    )


def test_altered_diffs_under_size_cap() -> None:
    """Fail at 20 MB so the operator can switch to keyed-per-card before
    the Astro build OOMs."""
    size = ALTERED_DIFFS.stat().st_size
    assert size < MAX_BYTES, (
        f"altered-diffs.json is {size / 1024 / 1024:.1f} MB, "
        f"over the {MAX_BYTES / 1024 / 1024:.0f} MB gate. Switch to "
        "keyed-per-card JSON (`web/src/data/altered-diffs/<card_id>.json`) "
        "and lazy-import per route — see state.md Sprint 4i #6 / PR #72 "
        "laverna P3 for context."
    )
