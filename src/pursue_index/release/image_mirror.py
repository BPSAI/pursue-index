"""IMG r2-mirror stage + preflight for the operated release path.

PDFs are content-addressed into ``r2-mirror/archive/<sha>.pdf`` by
``pdf_mirror``; A/V stages inline. Images had no stage, so their
``images/<card_id>/<asset_filename>`` bytes never reached the NAS archive.

For each IMG card the expected sha is the registry's newest ``byte_sha256``
(the same trust rule the vision path uses, via ``load_registry_rows``) and
the target is the registry ``archive_key`` under the mirror root, resolved by
``mirror_path_for`` (the one rule the preflight and the vision reader share). Idempotent and sha-verified; a
mismatch never writes and an existing differing target is never overwritten.

Pure filesystem I/O only: no network, no credentials.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pursue_index.card_id import CARD_ID_PATTERN
from pursue_index.config import settings
from pursue_index.download.downloader import asset_path_for
from pursue_index.release.exclusive_publish import (
    EXISTING_MATCH,
    PUBLISHED,
    publish_exclusive,
    sha256_file,
)
from pursue_index.row_key import row_keys
from pursue_index.vision.img_source import (
    BadArchiveKeyError,
    load_registry_rows,
    mirror_path_for,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "gif", "webp", "tif", "tiff"})
_NON_IMG_ASSET_TYPES = frozenset({"PDF", "VID", "AUD"})

MIRRORED = "mirrored"
ALREADY_PRESENT = "already_present"
SOURCE_MISSING = "source_missing"
SHA_MISMATCH = "sha_mismatch"
TARGET_MISMATCH = "target_mismatch"
NO_REGISTRY_ROW = "no_registry_row"
UNSAFE_SOURCE = "unsafe_source"
BAD_ARCHIVE_KEY = "bad_archive_key"
OUTCOMES = (
    MIRRORED,
    ALREADY_PRESENT,
    SOURCE_MISSING,
    SHA_MISMATCH,
    TARGET_MISMATCH,
    NO_REGISTRY_ROW,
    UNSAFE_SOURCE,
    BAD_ARCHIVE_KEY,
)
_FAILURES = frozenset(OUTCOMES) - {MIRRORED, ALREADY_PRESENT}


@dataclass(frozen=True)
class UnresolvedCard:
    """A worklist id the manifest cannot resolve to an IMG row; always a failure."""

    card_id: str
    asset_filename: str = ""


@dataclass
class ImageMirrorReport:
    """Outcome of ``run_image_mirror``: per-row ``(outcome, detail)``, keyed by row key."""

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
    details: dict[str, str] = field(default_factory=dict)  # row key -> reason


def _expected(card, rows: dict[str, dict]) -> tuple[str, Path] | tuple[str, str]:
    """``(sha, mirror-relative key)`` or ``(outcome, reason)`` for a refusal."""
    row = rows.get(card.card_id)
    if row is None:
        return NO_REGISTRY_ROW, "no registry row"
    sha = str(row["byte_sha256"])
    if not _SHA256_RE.fullmatch(sha):
        return NO_REGISTRY_ROW, f"registry byte_sha256 {sha!r} is not 64 lowercase hex digits"
    try:
        key = mirror_path_for(Path(), row)
    except BadArchiveKeyError as exc:
        return BAD_ARCHIVE_KEY, str(exc)
    if key.suffix.lstrip(".").lower() not in _IMAGE_EXTS:
        return BAD_ARCHIVE_KEY, f"archive_key extension {key.suffix[:12]!r} is not an image type"
    return sha, key


def _source_path(card, images_root: Path) -> Path | str:
    """The card's ``images/`` file, or the reason it is unsafe.

    The layout is the downloader's (``asset_path_for``); the id and file name
    come from an upstream scrape, so they are checked before any path is built.
    """
    name = card.asset_filename or ""
    if not CARD_ID_PATTERN.fullmatch(str(card.card_id)):
        return f"card_id {str(card.card_id)[:40]!r} is not 16 lowercase hex characters"
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
        or Path(name).is_absolute()
    ):
        return f"asset_filename {name[:80]!r} is not a bare file name"
    canonical = asset_path_for(card)
    if canonical is None:
        return ""  # no downloadable asset: nothing to copy
    try:
        src = images_root / canonical.relative_to(settings.image_dir)
    except ValueError:
        return f"source {name[:80]!r} is outside the images dir"
    if not src.resolve().is_relative_to(images_root.resolve()):
        return f"source {name[:80]!r} resolves outside the images root"
    return src


def select_image_cards(
    card_ids: list[str], manifest_cards: list[dict]
) -> tuple[list[str], dict[str, str]]:
    """Split a worklist into IMG cards and reported non-IMG skips.

    Returns ``(in_scope, skipped)``; ``skipped`` maps card_id -> the asset
    types it carries. Fails closed: an id absent from the manifest, or with a
    row lacking ``asset_type``, stays in scope and is gated normally.
    """
    types: dict[str, set[str | None]] = {}
    for card in manifest_cards:
        cid = card.get("card_id")
        if cid:
            types.setdefault(cid, set()).add(card.get("asset_type"))
    in_scope: list[str] = []
    skipped: dict[str, str] = {}
    for cid in card_ids:
        seen = types.get(cid)
        # Fails closed like select_pdf_cards: skip only an id whose every row
        # is a known non-IMG type; unknown or untyped ids stay gated.
        if seen and seen <= _NON_IMG_ASSET_TYPES:
            skipped[cid] = "+".join(sorted(str(t) for t in seen))
        else:
            in_scope.append(cid)
    return in_scope, skipped


def _publish_exclusive(tmp: Path, target: Path, sha: str) -> tuple[str, str]:
    """Publish ``tmp`` as ``target`` without overwriting; map to a mirror outcome."""
    status, actual = publish_exclusive(tmp, target, sha)
    if status == PUBLISHED:
        return MIRRORED, ""
    if status == EXISTING_MATCH:
        return ALREADY_PRESENT, ""
    return TARGET_MISMATCH, f"{target.name} holds sha {actual[:12]}, expected {sha[:12]}"


def _mirror_one(card, rows, images_root: Path, mirror_root: Path) -> tuple[str, str]:
    if isinstance(card, UnresolvedCard):
        return UNSAFE_SOURCE, "card is not an IMG row in the manifest"
    src = _source_path(card, images_root)
    if isinstance(src, str) and src:
        return UNSAFE_SOURCE, src
    exp = _expected(card, rows)
    if exp[0] in (NO_REGISTRY_ROW, BAD_ARCHIVE_KEY):
        return exp[0], str(exp[1])
    sha, key = exp
    target = mirror_root / key
    if target.is_file():
        actual = sha256_file(target)
        if actual == sha:
            return ALREADY_PRESENT, ""
        return TARGET_MISMATCH, f"{target.name} holds sha {actual[:12]}, expected {sha[:12]}"
    if not src or not src.is_file():
        return SOURCE_MISSING, f"no source at images/{card.card_id}/{card.asset_filename}"
    actual = sha256_file(src)
    if actual != sha:
        return SHA_MISMATCH, f"source sha {actual[:12]} != registry byte_sha256 {sha[:12]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    shutil.copy2(src, tmp)
    if sha256_file(tmp) != sha:
        tmp.unlink(missing_ok=True)
        return SHA_MISMATCH, "post-copy sha verification failed"
    return _publish_exclusive(tmp, target, sha)


def _keyed(cards) -> list[tuple[str, object]]:
    """``(row key, card)`` per in-scope row; rows sharing a card_id stay distinct."""
    cards = list(cards)
    keys = row_keys([{"card_id": c.card_id} for c in cards])
    return list(zip(keys, cards, strict=True))


def run_image_mirror(
    cards, *, images_root: Path, mirror_root: Path, registry_path: Path | None
) -> ImageMirrorReport:
    """Mirror each IMG row into ``r2-mirror/archive/<sha>.<ext>``.

    Never aborts mid-batch: each row gets an outcome and the rest continue.
    """
    rows = load_registry_rows(registry_path)
    report = ImageMirrorReport()
    for key, card in _keyed(cards):
        report.results[key] = _mirror_one(card, rows, images_root, mirror_root)
    return report


def verify_image_mirror(
    cards, *, mirror_root: Path, registry_path: Path | None
) -> ImageMirrorPreflight:
    """Fail-fast preflight: every IMG row's archive copy exists and matches."""
    rows = load_registry_rows(registry_path)
    details: dict[str, str] = {}
    for key, card in _keyed(cards):
        if isinstance(card, UnresolvedCard):
            details[key] = "card is not an IMG row in the manifest"
            continue
        exp = _expected(card, rows)
        if exp[0] in (NO_REGISTRY_ROW, BAD_ARCHIVE_KEY):
            details[key] = str(exp[1])
            continue
        sha, rel = exp
        if not CARD_ID_PATTERN.fullmatch(str(card.card_id)):
            details[key] = f"card_id {str(card.card_id)[:40]!r} is not 16 lowercase hex characters"
        elif not (mirror_root / rel).is_file():
            details[key] = f"missing r2-mirror/{rel}"
        elif sha256_file(mirror_root / rel) != sha:
            details[key] = f"r2-mirror/{rel} sha mismatch"
    return ImageMirrorPreflight(ok=not details, details=details)
