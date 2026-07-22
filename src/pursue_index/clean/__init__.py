"""LLM-cleaned reading-text overlay.

The ``clean`` stage is a presentation-layer pass over OCR output: it fixes
obvious OCR errors (broken hyphenation, column-detection scrambles,
redaction-boundary glitches) WITHOUT changing meaning. Raw OCR remains the
canonical text for citation; cleaned text is opt-in via the reader UI's
``Cleaned`` toggle.
"""

from __future__ import annotations
