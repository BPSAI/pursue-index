"""Vision observation stage (pipeline stage 7).

Generates operator-reviewed image-observation sidecars for the two kinds of
content no OCR engine can turn into searchable text:

* **IMG-card assets** — cards whose ``asset_type == "IMG"`` (a photograph or
  illustration, not a document).
* **Image-only PDF pages** — pages with zero base OCR under the operated
  ``llm-dots`` engine (the same predicate the embed path uses in
  ``embed.store._read_card_pages``).

The sidecars share the frozen May/July image-observations schema so the
existing loader (``embed.image_observations``) reads fresh output unchanged and
feeds it into both the static search payload and the embed vectors.

Spend is operator-attended: the default ``pursue vision run`` is a
verify-before-spend preflight (eligible-vs-produced coverage, no API calls).
``--live-smoke <card_id>`` is the only live path and CI never invokes it.
"""

from __future__ import annotations

from pursue_index.vision.client import VISION_MODEL

__all__ = ["VISION_MODEL"]
