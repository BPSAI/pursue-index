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

__all__ = ["referenced_elsewhere"]

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
        stack: list[Any] = [reader.get_object(member)]
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
