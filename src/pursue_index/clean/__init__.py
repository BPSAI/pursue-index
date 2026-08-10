"""LLM-cleaned reading-text overlay.

The ``clean`` stage is a presentation-layer pass over OCR output: it fixes
obvious OCR errors (broken hyphenation, column-detection scrambles,
redaction-boundary glitches) WITHOUT changing meaning. Raw OCR remains the
canonical text for citation; cleaned text is opt-in via the reader UI's
``Cleaned`` toggle.
"""

from __future__ import annotations

# Spend ceiling shared by the clean pass and its QC pass.
#
# Both stages default to every PDF card in the manifest, so both are sized by
# the same unit of work: one release tranche. The ceiling is a backstop against
# a runaway pass, not a throttle — it is set generously enough that a tranche
# finishes in a single run, and each stage fails closed the moment it is
# reached rather than carrying on. Any run can name its own with
# ``--budget-usd``.
#
# One constant rather than one per stage, so a bare invocation of either stage
# is capped the same way and the two cannot come to mean different things.
TRANCHE_SPEND_CEILING_USD = 8.0

__all__ = ["TRANCHE_SPEND_CEILING_USD"]
