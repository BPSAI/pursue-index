"""LLM-cleaned reading-text overlay.

The ``clean`` stage is a presentation-layer pass over OCR output: it fixes
obvious OCR errors (broken hyphenation, column-detection scrambles,
redaction-boundary glitches) WITHOUT changing meaning. Raw OCR remains the
canonical text for citation; cleaned text is opt-in via the reader UI's
``Cleaned`` toggle.
"""

from __future__ import annotations

# Default spend ceiling shared by the clean pass and its QC pass.
#
# The value is a fail-closed backstop, not a throttle: it exists so that a
# pass which stops making progress — retrying, looping, or handed far more
# work than intended — ends by itself instead of running unbounded. Each
# stage stops the moment the ceiling is reached rather than carrying on, and
# any run can state its own with ``--budget-usd``.
#
# One constant rather than one per stage, so a bare invocation of either stage
# is capped the same way and the two cannot come to mean different things.
TRANCHE_SPEND_CEILING_USD = 8.0

__all__ = ["TRANCHE_SPEND_CEILING_USD"]
