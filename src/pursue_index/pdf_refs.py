"""Who references an object: the guard behind the ``metadata`` role.

A stream typed ``/Type /Metadata /Subtype /XML`` is only metadata when the
catalog's ``/Metadata`` entry is the sole reference to it. Referenced from
anything else (an annotation's appearance stream, an XObject, a page), it is
content that happens to carry a metadata type, and rewriting it is a content
change.
"""

from __future__ import annotations

from typing import Any

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from pursue_index import pdf_limits
from pursue_index.pdf_limits import Budget, LimitExceededError

__all__ = ["action_reachable", "referenced_elsewhere"]

ACTION_KEYS = ("/OpenAction", "/AA", "/Names")  # JavaScript, launch, embedded files

MAX_NODES = 10_000_000


def _children(obj: Any, skip_key: str | None) -> list[Any]:
    if isinstance(obj, dict):
        return [v for k, v in obj.items() if k != skip_key]
    return list(obj) if isinstance(obj, list) else []


def _object_numbers(reader: PdfReader) -> set[int]:
    nums = {n for table in reader.xref.values() for n in table}
    return nums | set(reader.xref_objStm)


def referenced_elsewhere(num: int, reader: PdfReader, budget: Budget) -> bool:
    """True iff any object in ``reader`` other than the catalog's
    ``/Metadata`` entry references object ``num`` (time- and node-capped)."""
    root = reader.trailer.raw_get("/Root")
    root_num = root.idnum if isinstance(root, IndirectObject) else None
    numbers = _object_numbers(reader)
    if len(numbers) > pdf_limits.MAX_XREF_ENTRIES:
        raise LimitExceededError("xref-entry-ceiling", f"{len(numbers)} objects")
    nodes = 0
    for member in sorted(numbers):
        budget.check()
        if member == num:
            continue
        first = reader.get_object(member)
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
                if obj.idnum == num:
                    return True
                continue  # other objects are visited as members in their own right
            stack.extend(_children(obj, skip))
            skip = None
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
