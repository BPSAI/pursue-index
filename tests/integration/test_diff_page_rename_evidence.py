"""R7C.13 AC: the built ``/diff`` page carries a rename's byte-change evidence.

D042 (``a0f6663169c21caf`` -> ``ff3939f95d878062``) is a real approved
rename whose ``data/card-aliases.json`` row records a metadata-only re-save
with both byte shas. ``web/src/pages/diff.astro`` imports that file at build
time and hands it to ``DiffIsland`` (``client:load``).

``DiffIsland`` fetches its snapshots after hydration, so the RENAMED rows
are drawn in the browser, never in the static HTML. What a build CAN prove
is the two halves that browser render needs, both from the real artifact:

  * the page's island props carry D042's ``change_nature`` and full shas;
  * the island's client bundle ships the RENAMED-row evidence markup
    (``DiffRenamedSection``'s ``nature of change`` / ``byte sha256`` titles).

The row text itself (``metadata-only`` + ``d52431b354af → ca9563779824``)
is pinned by ``web/src/components/diff-helpers-renamed.test.ts``.

Skips when ``web/dist`` is absent: CI runs ``npm run build`` first.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DIST = _REPO_ROOT / "web" / "dist"
_DIFF_PAGE = _DIST / "diff" / "index.html"
OLD_SHA = "d52431b354af55b1e86cb454e61fd61993af3b023a38f2d9e014a9c9d18d16b4"
NEW_SHA = "ca9563779824e306f11393612fe6503f39877c6d5be03e77c875e928ee116b54"


def _page() -> str:
    if not _DIFF_PAGE.is_file():
        pytest.skip("web/dist/diff/index.html not present — run npm run build first")
    return html.unescape(_DIFF_PAGE.read_text(encoding="utf-8"))


def _diff_island_props(page: str) -> str:
    for island in re.findall(r"<astro-island\b[^>]*>", page):
        if "DiffIsland" in island:
            return island
    pytest.fail("no DiffIsland astro-island on the built /diff page")


def test_diff_page_props_carry_d042_byte_change() -> None:
    props = _diff_island_props(_page())
    d042 = props[props.index("a0f6663169c21caf"):]
    d042 = d042[: d042.index("}")]  # just the D042 alias object
    assert "ff3939f95d878062" in d042
    assert "metadata-only" in d042
    assert OLD_SHA in d042 and NEW_SHA in d042


def test_diff_island_bundle_renders_the_evidence() -> None:
    island = _diff_island_props(_page())
    url = re.search(r'component-url="[^"]*/_astro/([^"/]+)"', island)
    assert url, "DiffIsland island has no /_astro/ component-url"
    bundle = (_DIST / "_astro" / url.group(1)).read_text(encoding="utf-8")
    assert "nature of change" in bundle
    assert "byte sha256: " in bundle
