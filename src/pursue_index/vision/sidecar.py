"""Sidecar schema: construction + validation for the vision stage.

The frozen May/July image-observations artifacts vary page-to-page (the May
helicopter-case pages carry sensor-specific keys; the July residual pages carry
``description``/``visible_text``), but every sidecar shares a stable core:
``card_id``, ``schema_version``, ``our_pass.model``, and a ``pages`` list whose
entries each have a ``page`` number and an ``observations`` list. These models
capture that core with ``extra="allow"`` so both frozen shapes — and our fresh
output — validate against the same contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

# Method/context strings recorded in ``our_pass`` for provenance, matching the
# July residual-pages artifact's vocabulary.
_METHOD = "direct-vision-examination-via-pursue-vision"
_DEFAULT_CONTEXT = "vision-observation-generator"


class Observation(BaseModel):
    """One structured claim about the image."""

    model_config = ConfigDict(extra="allow")

    claim: str
    kind: str = "observation"
    confidence: str | None = None


class SidecarPage(BaseModel):
    """One examined page/image within a sidecar."""

    model_config = ConfigDict(extra="allow")

    page: int
    observations: list[Observation] = []


class Sidecar(BaseModel):
    """A card's image-observation sidecar."""

    model_config = ConfigDict(extra="allow")

    card_id: str
    schema_version: int
    our_pass: dict[str, Any]
    pages: list[SidecarPage]


def validate_sidecar(data: dict[str, Any]) -> Sidecar:
    """Validate ``data`` against the frozen image-observations schema.

    Raises ``pydantic.ValidationError`` on any deviation from the core contract
    (missing ``pages``, a page without a ``page`` number, etc.). Extra keys are
    preserved, so schema-rich May sidecars validate unchanged.
    """
    return Sidecar.model_validate(data)


def normalize_observations(value: Any) -> list[dict[str, Any]]:
    """The entries of ``value`` that satisfy the ``Observation`` contract.

    An observation is an object carrying a non-empty ``claim``; that is what
    the sidecar schema defines and what the searchable text renders. Anything
    else in the list — a bare string, an object with no claim — carries nothing
    a reader could retrieve and is left out, so a reply whose shape differs
    from the requested one still yields a valid page. Extra keys are kept, and
    ``kind`` defaults to the ordinary observation kind.
    """
    entries: list[dict[str, Any]] = []
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict):
            continue
        claim = str(entry.get("claim", "") or "").strip()
        if not claim:
            continue
        normalized = dict(entry)
        normalized["claim"] = claim
        normalized.setdefault("kind", "observation")
        entries.append(normalized)
    return entries


def page_has_content(page: dict[str, Any]) -> bool:
    """True when a page entry carries text a reader could retrieve.

    A page contributes content through its prose, its transcribed visible
    text, or at least one observation. A page with none of the three describes
    nothing, so it is not something coverage can be counted from.
    """
    for key in ("description", "visible_text"):
        if str(page.get(key, "") or "").strip():
            return True
    return bool(page.get("observations"))


def _normalize_page(page: dict[str, Any], page_no: int | None = None) -> dict[str, Any]:
    """Ensure a page dict carries a ``page`` number and valid ``observations``."""
    out = dict(page)
    if page_no is not None:
        out["page"] = page_no
    out.setdefault("page", page.get("page"))
    out["observations"] = normalize_observations(out.get("observations"))
    return out


def build_sidecar(
    *,
    card_id: str,
    title: str,
    model: str,
    pages: list[dict[str, Any]],
    session_id: str | None = None,
    context: str = _DEFAULT_CONTEXT,
) -> dict[str, Any]:
    """Build a sidecar dict in the frozen schema from examined ``pages``.

    Each entry in ``pages`` is an examination result (``image_type`` /
    ``description`` / ``visible_text`` / ``observations``) that already carries
    its ``page`` number. The returned dict validates against ``validate_sidecar``
    and is read unchanged by ``embed.image_observations.load_observation_text``.
    """
    normalized = [_normalize_page(p) for p in pages]
    sidecar: dict[str, Any] = {
        "card_id": card_id,
        "title": title,
        "schema_version": 1,
        "operator": "primary",
        "decided_at": datetime.now(UTC).isoformat(),
        "our_pass": {
            "model": model,
            "method": _METHOD,
            "context": context,
        },
        "pages": normalized,
    }
    if session_id is not None:
        sidecar["session_id"] = session_id
    validate_sidecar(sidecar)
    return sidecar
