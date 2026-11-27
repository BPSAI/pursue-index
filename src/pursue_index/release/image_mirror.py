"""IMG r2-mirror stage + preflight for the operated release path.

PDFs are content-addressed into ``r2-mirror/archive/<sha>.pdf`` by
``pdf_mirror``; A/V stages inline. Images had no stage, so their
``images/<card_id>/<asset_filename>`` bytes never reached the NAS archive.

For each IMG card the expected sha is the registry's newest ``byte_sha256``
(the same trust rule the vision path uses, via ``load_registry_rows``) and
the target is ``archive/<sha>.<ext>`` with ``ext`` taken from the registry
``archive_key`` so the name matches R2. Idempotent and sha-verified; a
mismatch never writes and an existing differing target is never overwritten.

Pure filesystem I/O only: no network, no credentials.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pursue_index.vision.img_source import load_registry_rows

_ARCHIVE_SUBDIR = "archive"
_CHUNK = 1 << 20
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

MIRRORED = "mirrored"
ALREADY_PRESENT = "already_present"
SOURCE_MISSING = "source_missing"
SHA_MISMATCH = "sha_mismatch"
TARGET_MISMATCH = "target_mismatch"
NO_REGISTRY_ROW = "no_registry_row"
MISSING = "missing"
OUTCOMES = (
    MIRRORED,
    ALREADY_PRESENT,
    SOURCE_MISSING,
    SHA_MISMATCH,
    TARGET_MISMATCH,
    NO_REGISTRY_ROW,
)
_FAILURES = frozenset(OUTCOMES) - {MIRRORED, ALREADY_PRESENT}


@dataclass
class ImageMirrorReport:
    """Outcome of ``run_image_mirror``: per-card ``(outcome, detail)``."""

    results: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(OUTCOMES, 0)
        for outcome, _ in self.results.values():
            out[outcome] += 1
        return out

    @property
    def ok(self) -> bool:
        return not any(o in _FAILURES for o, _ in self.results.values())


@dataclass
class ImageMirrorPreflight:
    """Outcome of ``verify_image_mirror``; ``details`` holds failing cards."""

    ok: bool
    details: dict[str, str] = field(default_factory=dict)  # card_id -> reason


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _expected(card, rows: dict[str, dict]) -> tuple[str, str] | str:
    """``(sha, ext)`` from the newest registry row, else a reason string."""
    row = rows.get(card.card_id)
    if row is None:
        return "no registry row"
    sha = str(row["byte_sha256"])
    if not _SHA256_RE.fullmatch(sha):
        return f"registry byte_sha256 {sha!r} is not 64 lowercase hex digits"
    ext = Path(str(row.get("archive_key") or "")).suffix or Path(card.asset_filename or "").suffix
    return sha, ext


def _target(mirror_root: Path, sha: str, ext: str) -> Path:
    return mirror_root / _ARCHIVE_SUBDIR / f"{sha}{ext}"


def select_image_cards(
    card_ids: list[str], manifest_cards: list[dict]
) -> tuple[list[str], dict[str, str]]:
    """Split a worklist into IMG cards and reported non-IMG skips.

    Returns ``(in_scope, skipped)``; ``skipped`` maps card_id -> the asset
    types it carries (``unknown`` for an id absent from the manifest). An id
    is in scope when any of its manifest rows is IMG.
    """
    types: dict[str, set[str]] = {}
    for card in manifest_cards:
        cid = card.get("card_id")
        if cid:
            types.setdefault(cid, set()).add(str(card.get("asset_type")))
    in_scope: list[str] = []
    skipped: dict[str, str] = {}
    for cid in card_ids:
        seen = types.get(cid)
        if seen and "IMG" in seen:
            in_scope.append(cid)
        else:
            skipped[cid] = "+".join(sorted(seen)) if seen else "unknown"
    return in_scope, skipped


def _mirror_one(card, rows, images_root: Path, mirror_root: Path) -> tuple[str, str]:
    exp = _expected(card, rows)
    if isinstance(exp, str):
        return NO_REGISTRY_ROW, exp
    sha, ext = exp
    target = _target(mirror_root, sha, ext)
    if target.is_file():
        actual = _sha256_file(target)
        if actual == sha:
            return ALREADY_PRESENT, ""
        return TARGET_MISMATCH, f"{target.name} holds sha {actual[:12]}, expected {sha[:12]}"
    src = images_root / card.card_id / (card.asset_filename or "")
    if not card.asset_filename or not src.is_file():
        return SOURCE_MISSING, f"no source at images/{card.card_id}/{card.asset_filename}"
    actual = _sha256_file(src)
    if actual != sha:
        return SHA_MISMATCH, f"source sha {actual[:12]} != registry byte_sha256 {sha[:12]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    shutil.copy2(src, tmp)
    if _sha256_file(tmp) != sha:
        tmp.unlink(missing_ok=True)
        return SHA_MISMATCH, "post-copy sha verification failed"
    tmp.replace(target)
    return MIRRORED, ""


def run_image_mirror(
    cards, *, images_root: Path, mirror_root: Path, registry_path: Path | None
) -> ImageMirrorReport:
    """Mirror each IMG card into ``r2-mirror/archive/<sha>.<ext>``.

    Never aborts mid-batch: each card gets an outcome and the rest continue.
    """
    rows = load_registry_rows(registry_path)
    report = ImageMirrorReport()
    for card in cards:
        report.results[card.card_id] = _mirror_one(card, rows, images_root, mirror_root)
    return report


def verify_image_mirror(
    cards, *, mirror_root: Path, registry_path: Path | None
) -> ImageMirrorPreflight:
    """Fail-fast preflight: every IMG card's archive copy exists and matches."""
    rows = load_registry_rows(registry_path)
    details: dict[str, str] = {}
    for card in cards:
        exp = _expected(card, rows)
        if isinstance(exp, str):
            details[card.card_id] = exp
            continue
        sha, ext = exp
        target = _target(mirror_root, sha, ext)
        if not target.is_file():
            details[card.card_id] = f"missing r2-mirror/archive/{sha[:12]}…{ext}"
        elif _sha256_file(target) != sha:
            details[card.card_id] = f"r2-mirror/archive/{sha[:12]}…{ext} sha mismatch"
    return ImageMirrorPreflight(ok=not details, details=details)


def render_image_mirror_report(report: ImageMirrorReport) -> str:
    """Operator-facing summary for ``pursue storage mirror-images``."""
    lines = ["### Image r2-mirror stage", ""]
    lines += [f"* {name}: {n}" for name, n in report.counts.items()]
    for cid, (outcome, detail) in report.results.items():
        if outcome in _FAILURES:
            lines.append(f"    * `{cid}` — {outcome}: {detail}")
    lines += ["", f"**All in-scope images mirrored:** {'yes' if report.ok else 'NO'}"]
    return "\n".join(lines)


def render_image_verify(pf: ImageMirrorPreflight) -> str:
    """Operator-facing summary for ``pursue storage verify-image-mirror``."""
    lines = ["### Image r2-mirror preflight", ""]
    if pf.ok:
        lines.append("**All in-scope image cards have their r2-mirror copy:** yes")
        return "\n".join(lines)
    lines.append(f"**MISSING or wrong mirror for {len(pf.details)} card(s):**")
    lines += [f"* `{cid}` — {why}" for cid, why in pf.details.items()]
    lines += [
        "",
        "> Run `pursue storage mirror-images --worklist <file>` to stage them, then re-verify.",
    ]
    return "\n".join(lines)
