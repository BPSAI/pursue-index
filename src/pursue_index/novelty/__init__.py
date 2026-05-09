"""Novelty detection: PURSUE pages vs prior public-archive reference corpora.

The chat surface answers "what does this corpus say." This module answers
"of these N pages, which are genuinely new vs. previously disclosed in
older FOIA archives." Reuses the embed pipeline's vector format
(``vectors.bin`` float32 + ``index.json``); the comparison is cosine
top-1 per PURSUE page against the reference index, aggregated to
card-level ``disclosure_status``.
"""

from __future__ import annotations

__all__: list[str] = []
