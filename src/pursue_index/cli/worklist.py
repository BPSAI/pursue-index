"""Shared ``--worklist`` helpers for the heavy ingest executors.

A *worklist* is a plain-text file of card_ids (one per line; blanks and
``#`` comments ignored, an optional ``\\treason`` suffix on each card_id line
ignored by readers) that scopes ``download``/``ocr``/``clean``/``embed``/
``vision``/``mirror-pdfs``/``verify-mirror`` to a detected tranche's
genuinely-new-or-changed cards instead of the full corpus.
``pursue ingest run --from-diff`` writes this file from
``pursue_index.ingest_scope.scope_worklist``.

Every worklist written by ``ingest run --from-diff`` carries a
``# tranche: <sha>`` header naming the promoted tranche's full csv_sha256.
Every consumer below MUST validate that header against the manifest it was
given before trusting the worklist's card_ids -- a worklist left over from an
earlier tranche (or one with no header at all) must never be silently
applied to today's manifest (R7C.1 / #168: this is what let a stale
``ocr --force`` run against last tranche's scope). ``require_worklist_tranche``
/ ``WorklistTrancheError`` is that one check; every call site here routes
through it.

``download``/``ocr`` are manifest-driven, so ``apply_worklist`` subsets
``manifest.cards`` before the async fan-out. ``embed``/``vision``/``clean``
read directories or OCR dirs directly, so they consume ``worklist_card_ids``
as an ``only_cards`` filter. ``mirror-pdfs``/``verify-mirror`` call
``read_worklist`` directly (via their own tranche check) because they key off
``r2-mirror/`` paths, not a ``Manifest`` object. A ``None`` path (flag
omitted) is the full-corpus escape hatch — a no-op, no tranche check.
"""

from __future__ import annotations

from pathlib import Path

import typer

from pursue_index.scrape.types import Manifest

_HEADER_PREFIX = "# tranche:"


class WorklistTrancheError(Exception):
    """A worklist's tranche header is missing, or doesn't match the
    promoted manifest. Names both shas so the CLI error is actionable."""

    def __init__(self, path: Path, promoted_sha: str, found_sha: str | None):
        self.path = path
        self.promoted_sha = promoted_sha
        self.found_sha = found_sha
        detail = found_sha if found_sha is not None else "none (no header)"
        super().__init__(
            f"worklist {path} is stale or unlabeled: its tranche header is "
            f"{detail!r}, but the promoted manifest is tranche {promoted_sha!r}. "
            "Rewrite the worklist for this tranche with "
            "`pursue ingest run --from-diff` before retrying."
        )


def worklist_header_tranche(path: Path) -> str | None:
    """The tranche sha named in ``path``'s ``# tranche: <sha>`` header line.

    The header must precede every card_id row -- a comment that merely
    happens to match the prefix after real rows have started doesn't count,
    so a worklist can't be fooled by a stray trailing comment.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_HEADER_PREFIX):
            return stripped[len(_HEADER_PREFIX):].strip()
        if not stripped.startswith("#"):
            break
    return None


def require_worklist_tranche(path: Path, promoted_sha: str) -> None:
    """Raise ``WorklistTrancheError`` unless ``path``'s header names ``promoted_sha``."""
    found = worklist_header_tranche(path)
    if found != promoted_sha:
        raise WorklistTrancheError(path, promoted_sha, found)


def exit_on_tranche_error(exc: WorklistTrancheError) -> None:
    """Echo ``exc`` to stderr and exit 1 — the one CLI-facing reaction every
    worklist-consuming command takes to a stale/mismatched/unlabeled worklist."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(1) from exc


def read_worklist(path: Path) -> list[str]:
    """Card_ids from a worklist file: one per line, blanks and #-comments
    ignored, an optional whitespace-separated reason tag dropped."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            ids.append(stripped.split()[0])
    return ids


def worklist_card_ids(path: Path | None, promoted_sha: str | None = None) -> set[str] | None:
    """The worklist as a set, or ``None`` when no worklist (full-corpus escape hatch).

    Raises ``WorklistTrancheError`` if ``path`` is given and its header
    doesn't name ``promoted_sha``. ``promoted_sha`` is required whenever
    ``path`` is not ``None`` -- a caller that forgets it is a bug, not a
    legitimate "skip the check" path.
    """
    if path is None:
        return None
    if not promoted_sha:
        raise ValueError("promoted_sha is required when a worklist path is given")
    require_worklist_tranche(path, promoted_sha)
    return set(read_worklist(path))


def apply_worklist(manifest: Manifest, path: Path | None) -> Manifest:
    """Subset ``manifest.cards`` to the worklist card_ids, preserving manifest order.

    A no-op returning the same object when ``path`` is ``None`` (the omitted-flag
    full-corpus escape hatch). Worklist ids absent from the manifest are ignored;
    un-listed cards are simply dropped (Class A / unaddressed Class C cards were
    never scoped). Raises ``WorklistTrancheError`` if the worklist's header
    doesn't name ``manifest.csv_sha256``.
    """
    if path is None:
        return manifest
    require_worklist_tranche(path, manifest.csv_sha256)
    wanted = set(read_worklist(path))
    cards = [c for c in manifest.cards if c.card_id in wanted]
    return manifest.model_copy(update={"cards": cards})
