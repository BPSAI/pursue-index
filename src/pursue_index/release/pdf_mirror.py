"""PDF r2-mirror stage + preflight guard for the operated release path.

ROOT CAUSE this closes (Release-4 fumble): the poll-driven PDF archive path
(``scripts/r2_archive_assets.py``) fetches PDF bytes and PUTs them to R2
(``archive/<sha>.pdf`` + ``<card_id>.pdf``) but NEVER writes the NAS-local
``r2-mirror/archive/<sha>.pdf`` copy. The A/V path stages to the NAS mirror
inline (``_ingest_tranche2_helpers.stage_to_nas``); PDFs did not. The curate
clean-qc judge renders page images from that NAS-local mirror, so a normal
tranche's freshly-OCR'd PDFs were absent from it and the judge silently
returned ``missing_page_image`` — it only surfaced when a downstream agent
staged the 14 R4 PDFs by hand.

This module makes the PDF mirror a deterministic, idempotent, sha-verified
stage: for each in-scope card it content-addresses ``pdfs/<card>/<file>.pdf``
into ``r2-mirror/archive/<pdf_sha256>.pdf`` (sha from ``ocr/<card>/meta.json``,
which is ``sha256`` of the exact bytes OCR read). ``verify_pdf_mirror`` is the
fail-fast preflight the ship path runs BEFORE clean-qc so a missing mirror
errors loudly instead of producing silent ``missing_page_image`` verdicts.

Pure filesystem I/O only — no network, no credentials.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

_META_NAME = "meta.json"
_ARCHIVE_SUBDIR = "archive"
_CHUNK = 1 << 20

# Asset types that have no PDF and are therefore outside this gate's remit.
# IMG cards carry a .jpg and are covered by the vision path at embed time;
# VID/AUD bytes are staged by the A/V ingest. Anything NOT listed here --
# including an unknown card or an absent asset_type -- stays in scope, so
# the gate fails closed rather than silently skipping a real PDF card.
_NON_PDF_ASSET_TYPES = frozenset({"IMG", "VID", "AUD"})


@dataclass(frozen=True)
class CardMirrorPlan:
    """A single card's mirror plan (what to do, decided before any copy)."""

    card_id: str
    sha: str | None
    source_pdf: Path | None
    target: Path | None
    state: str  # present | needs-copy | missing-meta | missing-source


@dataclass
class MirrorReport:
    """Outcome of ``run_pdf_mirror`` over a worklist."""

    mirrored: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # card_id -> reason

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class MirrorPreflight:
    """Outcome of ``verify_pdf_mirror`` — the fail-fast gate before clean-qc."""

    ok: bool
    missing: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)  # card_id -> reason


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pdf_sha(ocr_root: Path, card_id: str) -> str | None:
    """The ``pdf_sha256`` recorded in ``ocr/<card>/meta.json`` (or ``None``)."""
    meta = ocr_root / card_id / _META_NAME
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    sha = data.get("pdf_sha256") if isinstance(data, dict) else None
    return sha if isinstance(sha, str) and sha else None


def _find_source_pdf(pdfs_root: Path, card_id: str, sha: str) -> Path | None:
    """The card's source PDF. When several exist, the one hashing to ``sha``."""
    card_dir = pdfs_root / card_id
    if not card_dir.is_dir():
        return None
    candidates = sorted(p for p in card_dir.glob("*.pdf") if p.is_file())
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    for cand in candidates:
        if _sha256_file(cand) == sha:
            return cand
    return None


def _mirror_target(mirror_root: Path, sha: str) -> Path:
    return mirror_root / _ARCHIVE_SUBDIR / f"{sha}.pdf"


def plan_card(
    card_id: str, ocr_root: Path, pdfs_root: Path, mirror_root: Path
) -> CardMirrorPlan:
    """Decide the action for one card without copying anything."""
    sha = read_pdf_sha(ocr_root, card_id)
    if sha is None:
        return CardMirrorPlan(card_id, None, None, None, "missing-meta")
    target = _mirror_target(mirror_root, sha)
    if target.is_file():
        return CardMirrorPlan(card_id, sha, None, target, "present")
    source = _find_source_pdf(pdfs_root, card_id, sha)
    if source is None:
        return CardMirrorPlan(card_id, sha, None, target, "missing-source")
    return CardMirrorPlan(card_id, sha, source, target, "needs-copy")


def _execute_plan(plan: CardMirrorPlan) -> tuple[str, str | None]:
    """Perform the plan. Return ``(state, error_reason)``; sha-verified copy."""
    if plan.state == "present":
        return "present", None
    if plan.state == "missing-meta":
        return "error", "no meta.json/pdf_sha256 (OCR did not run for this card)"
    if plan.state == "missing-source":
        return "error", "no source PDF at pdfs/<card>/*.pdf to mirror"

    src, sha, target = plan.source_pdf, plan.sha, plan.target
    assert src is not None and sha is not None and target is not None
    actual = _sha256_file(src)
    if actual != sha:
        return "error", (
            f"source PDF sha {actual[:12]} != meta pdf_sha256 {sha[:12]} "
            "(source is not the bytes that were OCR'd)"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copy to a temp sibling then atomic-rename so a partial write never
    # looks like a present, verified mirror to the preflight guard.
    tmp = target.with_name(target.name + ".tmp")
    shutil.copy2(src, tmp)
    if _sha256_file(tmp) != sha:
        tmp.unlink(missing_ok=True)
        return "error", "post-copy sha verification failed"
    tmp.replace(target)
    return "mirrored", None


def select_pdf_cards(
    card_ids: list[str], manifest_cards: list[dict]
) -> tuple[list[str], dict[str, str]]:
    """Split a tranche worklist into PDF cards and reported non-PDF skips.

    A worklist is the whole tranche scope, not just its PDFs. Handing IMG/VID/AUD
    cards to a PDF mirror gate fails them for lacking a PDF they were never
    supposed to have. Returns ``(in_scope, skipped)`` where ``skipped`` maps
    card_id -> asset_type so the caller can report every exclusion — a silent
    skip here would look exactly like coverage.

    Fails closed: a card absent from the manifest, or one whose ``asset_type``
    is missing, stays IN scope and is gated normally.
    """
    types = {
        c.get("card_id"): c.get("asset_type")
        for c in manifest_cards
        if c.get("card_id")
    }
    in_scope: list[str] = []
    skipped: dict[str, str] = {}
    for card_id in card_ids:
        asset_type = types.get(card_id)
        if asset_type in _NON_PDF_ASSET_TYPES:
            skipped[card_id] = str(asset_type)
        else:
            in_scope.append(card_id)
    return in_scope, skipped


def run_pdf_mirror(
    card_ids: list[str], *, ocr_root: Path, pdfs_root: Path, mirror_root: Path
) -> MirrorReport:
    """Mirror every in-scope card's PDF into ``r2-mirror/archive/<sha>.pdf``.

    Idempotent (already-mirrored cards are a no-op) and sha-verified. Never
    aborts mid-batch: a per-card failure is recorded and the rest continue.
    """
    report = MirrorReport()
    for card_id in card_ids:
        plan = plan_card(card_id, ocr_root, pdfs_root, mirror_root)
        state, err = _execute_plan(plan)
        if state == "mirrored":
            report.mirrored.append(card_id)
        elif state == "present":
            report.present.append(card_id)
        else:
            report.errors[card_id] = err or "unknown error"
    return report


def verify_pdf_mirror(
    card_ids: list[str], *, ocr_root: Path, mirror_root: Path
) -> MirrorPreflight:
    """Fail-fast preflight: every in-scope PDF card has its mirror present.

    Credential-free and copy-free — the gate the ship path runs BEFORE the
    curate clean-qc/judge stage so a missing ``r2-mirror/archive/<sha>.pdf``
    errors loudly instead of yielding a silent ``missing_page_image`` verdict.
    """
    missing: list[str] = []
    details: dict[str, str] = {}
    for card_id in card_ids:
        sha = read_pdf_sha(ocr_root, card_id)
        if sha is None:
            details[card_id] = "no meta.json/pdf_sha256 (OCR did not run)"
            missing.append(card_id)
            continue
        if not _mirror_target(mirror_root, sha).is_file():
            details[card_id] = f"missing r2-mirror/archive/{sha[:12]}….pdf"
            missing.append(card_id)
    return MirrorPreflight(ok=not missing, missing=missing, details=details)


def render_mirror_report(report: MirrorReport) -> str:
    """Operator-facing summary for ``pursue storage mirror-pdfs``."""
    lines = [
        "### PDF r2-mirror stage",
        "",
        f"* mirrored (copied this run): {len(report.mirrored)}",
        f"* already present (no-op): {len(report.present)}",
        f"* errors: {len(report.errors)}",
    ]
    for card_id, reason in report.errors.items():
        lines.append(f"    * `{card_id}` — {reason}")
    lines.append("")
    lines.append(f"**All in-scope PDFs mirrored:** {'yes' if report.ok else 'NO'}")
    return "\n".join(lines)


def render_preflight(pf: MirrorPreflight) -> str:
    """Operator-facing summary for ``pursue storage verify-mirror``."""
    lines = ["### PDF r2-mirror preflight (before clean-qc)", ""]
    if pf.ok:
        lines.append("**All in-scope PDF cards have their r2-mirror copy:** yes")
        return "\n".join(lines)
    lines.append(f"**MISSING mirror for {len(pf.missing)} card(s):**")
    for card_id in pf.missing:
        lines.append(f"* `{card_id}` — {pf.details.get(card_id, 'missing')}")
    lines.append("")
    lines.append(
        "> Run `pursue storage mirror-pdfs --worklist <file>` to stage them, "
        "then re-verify. Do NOT run clean-qc until this passes — a missing "
        "mirror yields silent `missing_page_image` verdicts."
    )
    return "\n".join(lines)
