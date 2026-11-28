"""IMG r2-mirror stage + preflight for the operated release path.

PDFs are content-addressed into ``r2-mirror/archive/<sha>.pdf`` by
``pdf_mirror``; A/V stages inline. Images had no stage, so their
``images/<card_id>/<asset_filename>`` bytes never reached the NAS archive.

For each IMG card the expected sha is the registry's newest ``byte_sha256``
(the same trust rule the vision path uses, via ``load_registry_rows``) and
the target is the registry ``archive_key`` under the mirror root, resolved by
``img_mirror_path_for`` (the one rule the writer, the preflight and the vision
reader share: image extensions only; a legacy row with no ``archive_key`` gets
the same synthesized ``archive/<sha><ext>`` the reader uses). Idempotent and
sha-verified; a mismatch never writes and an existing differing target is
never overwritten. A symlink at the source is ``unsafe_source`` (checked before
the open, and refused again at open time via ``O_NOFOLLOW``, so one swapped in
between is not followed); a symlink at the target, dangling or live, is
``unsafe_target``. Neither is ever followed or written through. A real target
file whose sha differs stays ``target_mismatch``. The bytes hashed are the
bytes copied: both come from the one source descriptor.

Pure filesystem I/O only: no network, no credentials.
"""

from __future__ import annotations

import re
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
from pursue_index.release.image_mirror_io import (
    open_source_nofollow,
    sha256_stream,
    stage_temp,
)
from pursue_index.release.image_mirror_scope import (
    select_image_cards as select_image_cards,  # re-export: the CLI and tests import it here
)
from pursue_index.row_key import row_keys
from pursue_index.vision.img_source import (
    BadArchiveKeyError,
    img_mirror_path_for,
    load_registry_rows,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")

MIRRORED = "mirrored"
ALREADY_PRESENT = "already_present"
SOURCE_MISSING = "source_missing"
SHA_MISMATCH = "sha_mismatch"
TARGET_MISMATCH = "target_mismatch"
UNSAFE_TARGET = "unsafe_target"
NO_REGISTRY_ROW = "no_registry_row"
UNSAFE_SOURCE = "unsafe_source"
BAD_ARCHIVE_KEY = "bad_archive_key"
IO_ERROR = "io_error"
OUTCOMES = (
    MIRRORED,
    ALREADY_PRESENT,
    SOURCE_MISSING,
    SHA_MISMATCH,
    TARGET_MISMATCH,
    UNSAFE_TARGET,
    NO_REGISTRY_ROW,
    UNSAFE_SOURCE,
    BAD_ARCHIVE_KEY,
    IO_ERROR,
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


@dataclass(frozen=True)
class _Expected:
    """A row's expected ``sha`` and mirror-relative ``key``, or a refusal."""

    sha: str = ""
    key: Path = Path()
    refusal: str = ""  # an outcome name when the row is refused
    reason: str = ""


def _expected(card, rows: dict[str, dict]) -> _Expected:
    row = rows.get(card.card_id)
    if row is None:
        return _Expected(refusal=NO_REGISTRY_ROW, reason="no registry row")
    sha = str(row["byte_sha256"])
    if not _SHA256_RE.fullmatch(sha):
        reason = f"registry byte_sha256 {sha!r} is not 64 lowercase hex digits"
        return _Expected(refusal=NO_REGISTRY_ROW, reason=reason)
    try:
        key = img_mirror_path_for(Path(), row, card.asset_filename or "")
    except BadArchiveKeyError as exc:
        return _Expected(refusal=BAD_ARCHIVE_KEY, reason=str(exc))
    return _Expected(sha=sha, key=key)


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
    if src.is_symlink() and not src.exists():
        return f"source {name[:80]!r} is a dangling symlink"
    if not src.resolve().is_relative_to(images_root.resolve()):
        return f"source {name[:80]!r} resolves outside the images root"
    return src


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
    if exp.refusal:
        return exp.refusal, exp.reason
    sha = exp.sha
    target = mirror_root / exp.key
    if target.is_symlink():
        return UNSAFE_TARGET, f"{target.name} is a symlink; never followed or written through"
    if target.is_file():
        actual = sha256_file(target)
        if actual == sha:
            return ALREADY_PRESENT, ""
        return TARGET_MISMATCH, f"{target.name} holds sha {actual[:12]}, expected {sha[:12]}"
    if not src or not src.is_file():
        return SOURCE_MISSING, f"no source at images/{card.card_id}/{card.asset_filename}"
    inp = open_source_nofollow(src)
    if inp is None:
        return UNSAFE_SOURCE, f"source {src.name[:80]!r} is a symlink at open time"
    with inp:
        actual = sha256_stream(inp)
        if actual != sha:
            return SHA_MISMATCH, f"source sha {actual[:12]} != registry byte_sha256 {sha[:12]}"
        inp.seek(0)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = stage_temp(inp, target)
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
        try:
            report.results[key] = _mirror_one(card, rows, images_root, mirror_root)
        except OSError as exc:  # a failed row, not an aborted batch
            report.results[key] = (IO_ERROR, f"{type(exc).__name__}: {exc}"[:200])
    return report


def _verify_one(card, rows, mirror_root: Path) -> str:
    """Why this row's archive copy is missing or wrong, or ``""``."""
    if isinstance(card, UnresolvedCard):
        return "card is not an IMG row in the manifest"
    exp = _expected(card, rows)
    if exp.refusal:
        return exp.reason
    if not CARD_ID_PATTERN.fullmatch(str(card.card_id)):
        return f"card_id {str(card.card_id)[:40]!r} is not 16 lowercase hex characters"
    target = mirror_root / exp.key
    if not target.is_file():
        return f"missing r2-mirror/{exp.key}"
    if sha256_file(target) != exp.sha:
        return f"r2-mirror/{exp.key} sha mismatch"
    return ""


def verify_image_mirror(
    cards, *, mirror_root: Path, registry_path: Path | None
) -> ImageMirrorPreflight:
    """Fail-fast preflight: every IMG row's archive copy exists and matches."""
    rows = load_registry_rows(registry_path)
    details: dict[str, str] = {}
    for key, card in _keyed(cards):
        try:
            why = _verify_one(card, rows, mirror_root)
        except OSError as exc:  # a failing row, not an aborted preflight
            why = f"{IO_ERROR}: {type(exc).__name__}: {exc}"[:200]
        if why:
            details[key] = why
    return ImageMirrorPreflight(ok=not details, details=details)
