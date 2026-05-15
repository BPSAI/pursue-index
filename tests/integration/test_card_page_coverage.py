"""Release-gate AC: every manifest card_id has a built card detail page.

Tonight's lesson (2026-05-12, four hot-fixes on main): the only thing
keeping the deploy in lockstep with the pipeline was operator vigilance.
This test is the deterministic version of "did the build ship a page for
every card?" — runs after `cd web && npm run build` in CI and fails fast
if any card_id in `data/manifests/latest.json` has no corresponding
`web/dist/card/<card_id>/index.html`.

Aliased card_ids: the manifest holds the CURRENT card_id for each card;
old (renamed-away) card_ids are resolved by the worker via
`data/card-aliases.json`. Only the CURRENT card_id needs a built page;
old ids are served via 301/302 from the worker. So this test asserts
coverage for the manifest's card_id set, not for the historical union.

Run requires the Astro build to have produced web/dist/ first. If
web/dist/ is missing, the test fails with a clear "build first"
directive rather than skipping silently — a missing dist is itself a
release-gate failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LATEST_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"
_DIST_DIR = _REPO_ROOT / "web" / "dist"
_CARD_DIST = _DIST_DIR / "card"


def _load_manifest_card_ids() -> list[str]:
    data = json.loads(_LATEST_MANIFEST.read_text())
    return [c["card_id"] for c in data["cards"]]


def test_dist_dir_exists() -> None:
    """A missing web/dist is a release-gate failure, not a skip."""
    assert _DIST_DIR.is_dir(), (
        f"web/dist/ not found — run `cd web && npm run build` before this test. "
        f"Expected: {_DIST_DIR}"
    )


def test_every_manifest_card_has_a_dist_page() -> None:
    """For each card_id in latest.json, web/dist/card/<id>/index.html exists.

    Missing pages are the silent-404 class the operator caught manually
    on 2026-05-12 (video tile clicks → 404 in prod). This test catches
    them in CI.
    """
    if not _DIST_DIR.is_dir():
        pytest.skip("web/dist not present — test_dist_dir_exists will fail first")

    card_ids = _load_manifest_card_ids()
    missing: list[str] = []
    for cid in card_ids:
        page = _CARD_DIST / cid / "index.html"
        if not page.is_file():
            missing.append(cid)

    if missing:
        sample = ", ".join(missing[:10])
        more = f" (+{len(missing) - 10} more)" if len(missing) > 10 else ""
        pytest.fail(
            f"{len(missing)} of {len(card_ids)} manifest card_ids have no "
            f"web/dist/card/<id>/index.html: {sample}{more}.\n"
            f"Run `cd web && npm run build` after promoting the tranche, "
            f"and commit the result if the build output is tracked."
        )
