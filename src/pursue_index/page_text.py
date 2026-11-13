"""What a page's published text is: stdlib only, no package imports.

The search payload (``scripts/_search_pages.py``), the cleaned-page
provenance check (``clean.qc.page_provenance``) and the vision pass
(``embed.image_observations``) must agree on two things, so both live here
once:

* ``published_ocr_text`` -- the markup strip that turns a page's raw OCR text
  into the text ``pages.json`` publishes;
* ``OBSERVATIONS_HEADER`` -- the prefix that marks a page's text as our own
  vision description rather than OCR.

This module imports nothing outside the standard library, so a script can
load it by file path (``importlib.util.spec_from_file_location``) without
running the ``pursue_index`` package ``__init__`` and its third-party deps.
Keep it that way: ``tests/unit/test_page_text_is_a_leaf.py`` pins it.
"""

from __future__ import annotations

import re

# Bracketed header mirrors the retired Zhang ``[[IMAGE-DESCRIPTIONS via ...]]``
# marker so chat snippets and the citation surface make clear this text is our
# own vision pass, not OCR. ``worker/retrieve.js::makeSnippet`` centers on it
# naturally when a query matches inside the description.
OBSERVATIONS_HEADER = "[[IMAGE-OBSERVATIONS via pursue vision pass"

# Surya emits <b>/<u>/<i> markup even with math_mode=False; the corpus has no
# markup semantics, so pages.json publishes the text between the tags.
_OCR_MARKUP = re.compile(r"</?(?:b|u|i)>")


def published_ocr_text(raw: str) -> str:
    """The text pages.json publishes for a page's raw OCR text."""
    return _OCR_MARKUP.sub("", raw)
