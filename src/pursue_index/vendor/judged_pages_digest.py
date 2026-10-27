"""Cross-repo contract for the clean-qc bundle's per-card judged-page digest.

pursue-index's ``qc-coverage.json`` marks a card judged when the bundle's
``page_count`` matches the card's current page rows -- a re-OCR or
re-clean that changes page CONTENTS without changing the page COUNT
stays judged, undetected. ``judged_pages_digest`` fixes that: it folds
every page's :func:`page_sha256` into one digest the bundle carries per
card, so CI (which cannot read the NAS sidecars that record per-page
shas) can still detect content drift from the published bundle alone.

This module is dependency-free and standard-library-only on purpose:
pursue-index vendors it byte-for-byte (see the ``judged_pages_digest``
field on the bundle's card entries) rather than reimplementing the
contract, so the two repos can never compute diverging digests for the
same input. Do not add imports here, and do not change either function's
behaviour without updating the vendored copy in lockstep -- the shared
test-vector file ``tests/fixtures/judged_pages_digest_vectors.json``
pins the exact bytes both repos must reproduce.

Serialization (the digest's input bytes, pinned)
--------------------------------------------------

One line per judged page, ``"{page}\\t{source_page_sha256}"`` (page as a
base-10 integer, sha as lowercase hex), lines sorted by PAGE NUMBER
ASCENDING AS INTEGERS (not lexicographically -- page 10 sorts after
page 2, not between 1 and 2), joined with ``"\\n"`` with no trailing
newline, encoded as UTF-8. The digest is the lowercase hex SHA-256 of
those bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def page_sha256(text_cleaned: str) -> str:
    """SHA-256 hex digest of a page's cleaned source text.

    Hashes the UTF-8 bytes of ``text_cleaned`` exactly as decoded from
    its ``pages_cleaned.jsonl`` line -- no stripping, no newline or
    Unicode normalization. This is the single hash both pursue-curate
    (judging) and pursue-index's ``build_pages_cleaned.py`` compute over
    the same ``text_cleaned`` field.
    """
    return hashlib.sha256(text_cleaned.encode("utf-8")).hexdigest()


def judged_pages_digest(pages: Iterable[tuple[int, str]]) -> str:
    """Digest a card's judged pages, keyed by ``(page_number, source_page_sha256)``.

    See the module docstring for the pinned serialization this hashes
    over. Order of ``pages`` does not matter -- the lines are sorted by
    page number (as integers) before joining, so a caller handing pages
    in any order gets the same digest.
    """
    lines = [
        f"{page}\t{sha}" for page, sha in sorted(pages, key=lambda item: item[0])
    ]
    blob = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
