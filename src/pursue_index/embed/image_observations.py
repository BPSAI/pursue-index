"""Render operator-verified image-observation text for image-only pages.

The image-observations index (``web/src/data/image-observations/index.json``)
lists card_ids whose external Zhang VLM pass was quarantined and replaced by our
own vision examination. Each listed card has a sidecar ``<card_id>.json`` next to
the index. A subset of those cards carry pages with **zero base OCR** — genuinely
image-only pages (a photograph, a composite illustration, a blank folder cover)
that no OCR engine could turn into searchable text.

This module renders a faithful, searchable text blob per ``(card_id, page)`` from
the sidecars so those image-only pages still carry our own description in both the
static search payload (``pages.json``) and the embed vectors — the single source
that keeps keyword and vector retrieval in parity (the gap the retired Zhang pass
left behind).

Only pages whose base OCR is empty consume this text (the callers guard on that);
pages with real OCR keep their OCR verbatim, so the sidecars stay provenance-only
for those, matching the quarantine policy.
"""

from __future__ import annotations

import json
from pathlib import Path

# Bracketed header mirrors the retired Zhang ``[[IMAGE-DESCRIPTIONS via ...]]``
# marker so chat snippets and the citation surface make clear this text is our
# own vision pass, not OCR. ``worker/retrieve.js::makeSnippet`` centers on it
# naturally when a query matches inside the description.
OBSERVATIONS_HEADER = "[[IMAGE-OBSERVATIONS via pursue vision pass"

DEFAULT_MODEL = "claude-opus-4-8"


def _header(model: str) -> str:
    return f"{OBSERVATIONS_HEADER}, {model}]]"


def _observation_claims(page: dict) -> list[str]:
    claims: list[str] = []
    for obs in page.get("observations") or []:
        if isinstance(obs, dict):
            claim = str(obs.get("claim", "")).strip()
            if claim:
                claims.append(claim)
    return claims


def render_page_text(page: dict, model: str = DEFAULT_MODEL) -> str:
    """Compose the searchable text for one sidecar page entry.

    Robust to both sidecar schemas: the residual image-only pages carry a
    ``description``/``visible_text`` prose blob; the earlier helicopter-case
    bundles carry only structured ``observations``. Either way we emit the
    header, whatever prose exists, any transcribed text, and the observation
    claims — so a query matches on the concrete nouns a researcher would search.
    """
    parts: list[str] = [_header(model)]
    description = str(page.get("description", "") or "").strip()
    if description:
        parts.append(description)
    visible = str(page.get("visible_text", "") or "").strip()
    if visible:
        parts.append(f'Visible text: "{visible}"')
    claims = _observation_claims(page)
    if claims:
        parts.append("Observations:\n" + "\n".join(f"- {c}" for c in claims))
    return "\n\n".join(parts)


def observation_only_pages(
    obs_lookup: dict[tuple[str, int], str] | None,
    ocr_card_ids: set[str],
) -> list[tuple[str, int, str]]:
    """``(card_id, page, text)`` for pages whose only text is an observation.

    An image card carries no document to read, so it never gets a card
    directory under the OCR root and the ordinary walk cannot reach it. Its
    observation text is the whole of its searchable content, so it is emitted
    from here instead. Cards that DO have OCR output are excluded: their pages
    come from the walk, which already substitutes observation text for an
    empty page, and emitting them twice would put the same page in the payload
    under two texts. Returned in card_id then page order so a rebuild is
    deterministic.
    """
    if not obs_lookup:
        return []
    return [
        (card_id, page, text)
        for (card_id, page), text in sorted(obs_lookup.items())
        if card_id not in ocr_card_ids
    ]


def _load_sidecar(obs_dir: Path, card_id: str) -> dict | None:
    sidecar = obs_dir / f"{card_id}.json"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_observation_text(
    index_path: Path, obs_dir: Path | None = None
) -> dict[tuple[str, int], str]:
    """Return ``{(card_id, page): rendered_text}`` for every sidecar page.

    Reads the card_ids from ``index_path`` and each card's ``<card_id>.json``
    sidecar (from ``obs_dir``, defaulting to the index's own directory). A
    missing or malformed index, or a card with no sidecar, is skipped rather
    than raised — the loader must never break a build.
    """
    if not index_path.exists():
        return {}
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    obs_dir = obs_dir or index_path.parent
    out: dict[tuple[str, int], str] = {}
    for card_id in index.get("card_ids", []):
        sidecar = _load_sidecar(obs_dir, str(card_id))
        if sidecar is None:
            continue
        model = str(
            (sidecar.get("our_pass") or {}).get("model", DEFAULT_MODEL)
        )
        for page in sidecar.get("pages", []):
            if "page" not in page:
                continue
            out[(str(card_id), int(page["page"]))] = render_page_text(
                page, model
            )
    return out
