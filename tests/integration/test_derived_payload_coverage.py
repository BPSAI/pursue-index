"""Release-gate AC: every derived payload covers the current manifest.

Derived payloads under ``web/public/data/`` are rebuilt from the
manifest and from pages.json. CI already gated *freshness* for some
surfaces (llms.txt provenance, snapshot mirrors) but gated *coverage*
for none of them: no shipped artifact was ever asserted to cover the
sources it is derived from. So a tranche could land, the site could
build green, and the search index, atlas, posters or thumbnails could
still describe the previous release.

This module is that assertion, parametrized over
``tests.support.payload_specs.SPECS`` — the one place each payload's
eligibility predicate is written down, including what it legitimately
excludes (IMG-only cards carry no thumbnail; pages with no extracted
text carry no embedding).

Credential-free by construction: predicates read only repo-committed
files (``data/manifests/latest.json`` and ``web/public/data/pages.json``).
No NAS mount, no network, no environment variables — this runs in the
same sandbox as the other release-gate steps.

RED DEMONSTRATION (2026-08-08, real history, not a synthetic fixture)
---------------------------------------------------------------------
``tests/support/payload_coverage_red_demo.py`` materializes each spec's
payload *and* sources at a given revision (via ``git show``) and runs
these exact predicates over that tree. Two revisions were checked.

``0956858`` — the R5 promote (334 -> 375 cards). The tranche landed,
CI was green, and three derived payloads still described the previous
release::

    $ python -m tests.support.payload_coverage_red_demo 0956858

    web/public/data/embed_index.json does not match its eligibility predicate.
      eligible ((card_id, page)): 8723    shipped: 8443
      MISSING from payload (320): 09ab9032c16fbaa2:1, 0aa52db3ec97c002:1, ...
        (+300 more)
      STALE in payload, no longer eligible (40): 69f1874d972fb44c:16, ...
        (+20 more)
    web/public/data/atlas-layout.json does not match its eligibility predicate.
      eligible ((card_id, page)): 8723    shipped: 4127
      MISSING from payload (4608) / STALE in payload (12)
    web/public/data/video-posters/index.json does not match its predicate.
      eligible (card_id): 131    shipped: 60
      MISSING from payload (87): 002eaa383e76a277, 01765a63bbd3f02f, ...
        (+67 more)

    RED: 3 of 5 payloads fail against 0956858

320 pages with text that search could not reach, 4,608 documents absent
from the atlas, 87 A/V cards with no poster frame.

``f3ba027^`` — after the R5 rebuild but before the one-row-per-
(card_id, page) selection fix. Coverage is complete there, so only the
other half of the defect fires: 40 keys still shipped for pages the
predicate no longer admits (two cards that left the corpus, plus a
truncated document's dropped tail). ``RED: 2 of 5``.

Against HEAD the same harness prints ``PASS: 0 of 5``, which is what
this module asserts below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.payload_coverage import (
    CoverageResult,
    PayloadSpec,
    describe_failure,
    evaluate,
    json_loader,
)
from tests.support.payload_specs import SPECS

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# One loader for the whole module so pages.json is parsed once, not
# once per parametrized case.
_LOAD = json_loader(_REPO_ROOT)


@pytest.mark.parametrize("spec", SPECS, ids=[s.id for s in SPECS])
def test_payload_sources_are_committed_to_the_repo(spec: PayloadSpec) -> None:
    """The gate is credential-free: every input is a tracked file."""
    for rel in (*spec.sources, spec.payload):
        assert (_REPO_ROOT / rel).is_file(), (
            f"{rel} is missing from the checkout — the coverage gate for "
            f"{spec.payload} cannot run without it."
        )


@pytest.mark.parametrize("spec", SPECS, ids=[s.id for s in SPECS])
def test_payload_covers_its_eligible_manifest_entries(spec: PayloadSpec) -> None:
    """Shipped artifact vs. the entries its sources say it should hold.

    Failure names the offending ids (first 20, then a count) so the
    operator can tell a missed rebuild from a genuine corpus change
    without re-deriving the diff by hand.
    """
    result: CoverageResult = evaluate(spec, _LOAD)
    if not result.ok:
        pytest.fail(describe_failure(result))
