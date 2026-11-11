"""The post-dry-run check that a tranche scopes no content work.

``pursue ingest run --from-diff --dry-run`` writes two work-lists:

* ``data/ingest-worklist.txt`` -- PDF/IMG cards to download/OCR/embed,
  always rewritten, headed ``# tranche: <sha64>``;
* ``data/ingest-worklist-av.txt`` -- VID/AUD cards, written only when
  non-empty, headed ``# worklist for tranche <sha12> ...``.

The receipt alone cannot prove a tranche needs no OCR: the bytes-changed
scope comes from the asset registry, not the diff. So after the dry run both
lists must be empty for this tranche. The PDF/IMG list must exist and carry
this tranche's header (else the dry run did not do its job); an A/V list
headed for a different tranche is a leftover, not this tranche's scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pursue_index.cli.worklist import read_worklist, worklist_header_tranche

__all__ = ["AV_WORKLIST", "PDF_WORKLIST", "WorklistCheck", "WorklistError", "check_worklists"]

PDF_WORKLIST = Path("data") / "ingest-worklist.txt"
# Named by ``cli.ingest_from_diff.write_worklist_file(..., suffix="-av")``.
AV_WORKLIST = Path("data") / "ingest-worklist-av.txt"
_AV_HEADER = re.compile(r"#\s*worklist for tranche\s+([0-9a-f]{12})\b")


class WorklistError(RuntimeError):
    """The dry run did not leave a usable PDF/IMG work-list for this tranche."""


@dataclass(frozen=True)
class WorklistCheck:
    pdf_ids: list[str]
    av_ids: list[str]
    note: str

    @property
    def empty(self) -> bool:
        return not self.pdf_ids and not self.av_ids


def _av_header_sha12(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if (match := _AV_HEADER.match(line.strip())) is not None:
            return match.group(1)
    return None


def _av_ids(repo_root: Path, tranche_sha: str) -> tuple[list[str], str]:
    path = repo_root / AV_WORKLIST
    if not path.is_file():
        return [], "no A/V work-list written"
    header = _av_header_sha12(path)
    if header is not None and header != tranche_sha[:12]:
        return [], f"A/V work-list is for tranche {header}, ignored as a leftover"
    # Unheaded or headed for this tranche: its ids count (fail closed).
    return read_worklist(path), "A/V work-list read"


def check_worklists(repo_root: Path, tranche_sha: str) -> WorklistCheck:
    """Both work-lists' card ids for ``tranche_sha``; raises :class:`WorklistError`."""
    pdf = repo_root / PDF_WORKLIST
    if not pdf.is_file():
        raise WorklistError(f"{PDF_WORKLIST} was not written by the dry run")
    if worklist_header_tranche(pdf) != tranche_sha:
        raise WorklistError(f"{PDF_WORKLIST} is not headed for this tranche")
    av_ids, note = _av_ids(repo_root, tranche_sha)
    return WorklistCheck(read_worklist(pdf), av_ids, note)
