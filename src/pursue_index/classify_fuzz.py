"""Differential fuzz harness for ``tranche_bytes.classify_bytes``.

Generates (old, new) PDF pairs where ``new`` is ``old`` plus one hand-built
incremental update, mixing metadata-only edits (a new or rewritten Info
dictionary, XMP stream, indirect leaves they own) with content edits (page
content streams, images, annotation appearances, page dictionaries, resource
maps, a previously undefined object number an old page points at, a content
stream re-typed as XMP) over classic xref tables and xref streams.

Every pair is classified, and every ``metadata-only`` verdict is re-checked
by an independent oracle: PDFium (``pypdfium2``, a second PDF
implementation that shares no code with pypdf or ``pdf_update``) renders
every page of both files and extracts their text, page sizes and
rotations. A pair the classifier calls ``metadata-only`` that the oracle
sees differ is a finding; the run fails on any.

The reverse (``content-changed`` on a pair the oracle sees as equal) is the
classifier's documented bias toward the safe verdict and is only counted.

Bounded: a fixed iteration count and a wall-clock budget; deterministic for
a given seed. Reads and writes no credentials and no network.
"""


from __future__ import annotations

import hashlib
import random
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pursue_index.classify_fuzz_base import Layout, Update, append, build_base
from pursue_index.classify_fuzz_ops import BENIGN_OPS, CONTENT_OPS, Case, generate_case

__all__ = [
    "BENIGN_OPS",
    "CONTENT_OPS",
    "Case",
    "FuzzReport",
    "Layout",
    "Update",
    "append",
    "build_base",
    "generate_case",
    "oracle_difference",
    "run_fuzz",
]

# --------------------------------------------------------------------------
# Oracle: a second PDF implementation renders both files
# --------------------------------------------------------------------------


def _fingerprint(data: bytes) -> list[tuple[object, ...]]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    try:
        out = []
        for i in range(len(doc)):
            page = doc[i]
            bitmap = page.render(scale=0.5, may_draw_forms=True)
            pixels = hashlib.sha256(bytes(bitmap.buffer)).hexdigest()
            textpage = page.get_textpage()
            text = " ".join(textpage.get_text_bounded().split())
            out.append((page.get_size(), page.get_rotation(), bitmap.width, bitmap.height,
                        pixels, text))
            textpage.close()
            bitmap.close()
            page.close()
        return out
    finally:
        doc.close()


def oracle_difference(old: bytes, new: bytes) -> str | None:
    """Why PDFium sees the two files differ, or ``None`` when every page
    renders, measures, rotates and reads the same."""
    try:
        before = _fingerprint(old)
    except Exception as exc:  # noqa: BLE001 -- a broken base is a generator bug, not a finding
        raise RuntimeError(f"oracle cannot open the old file: {exc!r}") from exc
    try:
        after = _fingerprint(new)
    except Exception as exc:  # noqa: BLE001 -- unopenable new file is a difference
        return f"new file does not open: {exc!r}"
    if len(before) != len(after):
        return f"page count {len(before)} -> {len(after)}"
    labels = ("size", "rotation", "width", "height", "pixels", "text")
    for number, (a, b) in enumerate(zip(before, after, strict=True)):
        for label, x, y in zip(labels, a, b, strict=True):
            if x != y:
                return f"page {number} {label} differs"
    return None


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


@dataclass
class FuzzReport:
    seed: int
    cases: int = 0
    verdicts: Counter = field(default_factory=Counter)
    findings: list[tuple[Case, str]] = field(default_factory=list)
    safe_disagreements: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.findings and self.verdicts["metadata-only"] > 0

    def summary(self) -> str:
        return (f"classify fuzz seed={self.seed}: {self.cases} cases, "
                f"metadata-only {self.verdicts['metadata-only']}, "
                f"content-changed {self.verdicts['content-changed']}, "
                f"findings {len(self.findings)}, safe-side disagreements "
                f"{self.safe_disagreements}{' (time budget reached)' if self.timed_out else ''}")


def run_fuzz(
    iterations: int, seed: int, *, time_budget: float = 600.0, isolated: bool = False,
    findings_dir: Path | None = None,
) -> FuzzReport:
    """Classify ``iterations`` generated pairs (stopping early at
    ``time_budget`` seconds) and oracle-check every ``metadata-only``."""
    from pursue_index.tranche_bytes import METADATA_ONLY, classify_bytes

    rng = random.Random(seed)
    report = FuzzReport(seed=seed)
    deadline = time.monotonic() + time_budget
    with tempfile.TemporaryDirectory(prefix="classify-fuzz-") as scratch:
        old_path, new_path = Path(scratch) / "old.pdf", Path(scratch) / "new.pdf"
        for index in range(iterations):
            if time.monotonic() >= deadline:
                report.timed_out = True
                break
            case = generate_case(rng, index)
            old_path.write_bytes(case.old)
            new_path.write_bytes(case.new)
            verdict = classify_bytes(old_path, new_path, isolated=isolated)
            report.cases += 1
            report.verdicts[verdict] += 1
            difference = oracle_difference(case.old, case.new)
            if verdict == METADATA_ONLY and difference is not None:
                report.findings.append((case, difference))
                if findings_dir is not None:
                    _save(findings_dir, case, difference)
            elif verdict != METADATA_ONLY and difference is None and set(case.ops) <= set(BENIGN_OPS):
                report.safe_disagreements += 1
    return report


def _save(directory: Path, case: Case, difference: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"case-{case.index:05d}"
    (directory / f"{stem}-old.pdf").write_bytes(case.old)
    (directory / f"{stem}-new.pdf").write_bytes(case.new)
    (directory / f"{stem}.txt").write_text(f"ops: {', '.join(case.ops)}\noracle: {difference}\n")
