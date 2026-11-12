"""Who references an object: the guard behind the ``metadata`` role.

A stream typed ``/Type /Metadata /Subtype /XML`` is only metadata when the
catalog's ``/Metadata`` entry is the sole reference to it. Referenced from
anything else (an annotation's appearance stream, an XObject, a page), it is
content that happens to carry a metadata type, and rewriting it is a content
change.

The same rule covers the closure: a brand-new leaf object the update adds
for the ``/Info`` dictionary or the XMP stream (an indirect ``/Title``, an
indirect ``/Length``) must be referenced from nowhere but those objects. An
old page that pointed at a then-undefined object number (``/Rotate 12 0 R``
resolves to null) is changed by an update that defines it, whichever
metadata object also names it. ``referenced_outside`` scans pypdf's parsed
objects and ``raw_reference_in`` the raw bytes, since pypdf resolves (and
drops) an indirect stream ``/Length`` while parsing.
"""

from __future__ import annotations

import re
from typing import Any

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from pursue_index import pdf_limits
from pursue_index.pdf_limits import Budget, LimitExceededError

__all__ = ["action_reachable", "raw_reference_in", "referenced_elsewhere", "referenced_outside"]

ACTION_KEYS = ("/OpenAction", "/AA", "/Names")  # JavaScript, launch, embedded files

MAX_NODES = 10_000_000


def _children(obj: Any, skip_key: str | None) -> list[Any]:
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k != skip_key]
    return list(obj) if isinstance(obj, list) else []


def _object_ids(reader: PdfReader) -> set[tuple[int, int]]:
    """Every ``(number, generation)`` the xref defines. Objects inside object
    streams are generation 0. The generation is kept so an object defined at
    generation 1 or above is read as itself, not as ``N 0``."""
    ids = {(num, gen) for gen, table in reader.xref.items() for num in table}
    return ids | {(num, 0) for num in reader.xref_objStm}


def referenced_elsewhere(num: int, reader: PdfReader, budget: Budget) -> bool:
    """True iff any object in ``reader`` other than the catalog's
    ``/Metadata`` entry references object ``num`` (time- and node-capped)."""
    return referenced_outside({num}, {num}, reader, budget)


def referenced_outside(
    targets: set[int], allowed: set[int], reader: PdfReader, budget: Budget,
) -> bool:
    """True iff any object in ``reader`` outside ``allowed`` references one of
    ``targets``. The catalog's ``/Metadata`` entry and the xref streams' own
    dictionaries (they ARE the trailer) never count (time- and node-capped)."""
    if not targets:
        return False
    root = reader.trailer.raw_get("/Root")
    root_num = root.idnum if isinstance(root, IndirectObject) else None
    ids = _object_ids(reader)
    if len(ids) > pdf_limits.MAX_XREF_ENTRIES:
        raise LimitExceededError("xref-entry-ceiling", f"{len(ids)} objects")
    nodes = 0
    for member, generation in sorted(ids):
        budget.check()
        if member in allowed:
            continue
        first = reader.get_object(IndirectObject(member, generation, reader))
        if isinstance(first, dict) and first.get("/Type") == "/XRef":
            continue  # an xref stream's dict IS the trailer (/Root, /Info), not a reference
        stack: list[Any] = [first]
        skip = "/Metadata" if member == root_num else None
        while stack:
            obj = stack.pop()
            nodes += 1
            if nodes > MAX_NODES:
                raise LimitExceededError("ref-scan-node-cap", f"over {MAX_NODES}")
            if isinstance(obj, IndirectObject):
                if obj.idnum in targets:
                    return True
                continue  # other objects are visited as members in their own right
            stack.extend(_children(obj, skip))
            skip = None
    return False


# Object numbers are bounded by the xref ceiling; a longer digit run is not one.
# Between the tokens PDF allows any whitespace (NUL and form feed included) and
# comments (``%`` to end of line). Possessive quantifiers keep the separator
# linear: a run of comments has exactly one way to match.
_PDF_SEP = rb"(?:[\x00\t\n\x0c\r ]|%[^\r\n]*+)++"
_RAW_REF = re.compile(
    rb"(?<![\d.])(\d{1,10})" + _PDF_SEP + rb"\d{1,10}" + _PDF_SEP + rb"R(?![A-Za-z0-9])")
_RAW_SCAN_CHECK_EVERY = 4096


def raw_reference_in(data: bytes, targets: set[int], budget: Budget) -> bool:
    """True iff ``data`` holds the raw syntax ``N G R`` for any ``N`` in
    ``targets``. Conservative: a match inside stream data also counts.

    One fixed pattern, whatever the number of targets; each match's object
    number is looked up in the set, and the budget is checked as the scan
    goes."""
    if not targets:
        return False
    budget.check()
    for count, match in enumerate(_RAW_REF.finditer(data), 1):
        if int(match[1]) in targets:
            return True
        if count % _RAW_SCAN_CHECK_EVERY == 0:
            budget.check()
    budget.check()
    return False


def action_reachable(reader: PdfReader, budget: Budget) -> set[int]:
    """Object numbers reachable from the catalog's ``/OpenAction``, ``/AA`` or
    ``/Names``: where JavaScript, launch actions and embedded files live.

    An update touching any of them is never metadata-only, whatever role the
    object would otherwise play (an ``/Info`` dictionary can double as an
    ``/OpenAction``).
    """
    root = reader.trailer.get("/Root")
    found: set[int] = set()
    stack: list[Any] = [root.raw_get(k) for k in ACTION_KEYS if root is not None and k in root]
    nodes = 0
    while stack:
        budget.check()
        obj = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise LimitExceededError("ref-scan-node-cap", f"over {MAX_NODES}")
        if isinstance(obj, IndirectObject):
            if obj.idnum in found:
                continue
            found.add(obj.idnum)
            obj = reader.get_object(obj.idnum)
        stack.extend(_children(obj, None))
    return found
