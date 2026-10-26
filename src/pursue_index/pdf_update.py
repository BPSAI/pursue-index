"""Parse the single incremental-update section appended to a PDF.

``read_update(old, new, reader)`` assumes ``new`` starts with ``old`` and
reads the bytes after it as exactly ONE PDF incremental update: some
``N G obj ... endobj`` bodies, one cross-reference section (a classic
``xref`` table + ``trailer``, or an xref *stream*) whose ``/Prev`` is the
old file's final ``startxref``, then ``startxref``/``%%EOF``.

It is deliberately strict -- it returns ``None`` (not a clean update)
when anything is off, and every caller reads ``None`` as "content may have
changed":

  * more than one ``startxref``/``%%EOF`` in the appended bytes;
  * ``/Prev`` not equal to the old file's own final ``startxref``;
  * a hybrid (``/XRefStm``) or encrypted (``/Encrypt``) trailer;
  * a freed object other than object 0;
  * an in-use entry pointing back into the old bytes, or into an object
    stream (type-2 entries are not unpacked -- conservative by design);
  * any appended byte not accounted for by a declared object, the xref
    section or the final ``startxref``/``%%EOF`` (only whitespace and
    comments may sit between them), so an undeclared object cannot hide.

Object bodies are read with pypdf's tokenizer (``read_object``); the
section structure itself is parsed here, by hand, because pypdf merges
every section into one view and drops ``/Prev``.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.generic import DictionaryObject, PdfObject, StreamObject, read_object

__all__ = ["UpdateSection", "read_update"]

_TAIL = re.compile(rb"startxref\s+(\d+)\s*%%EOF\s*\Z")
_OBJ_HEADER = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_SUBSECTION = re.compile(rb"\s*(\d+)\s+(\d+)\s*")
_TABLE_ROW = re.compile(rb"(\d{10})\s(\d{5})\s([nf])\s*")
_FILLER = re.compile(rb"(?:\s|%[^\r\n]*)*")
_REF = re.compile(rb"(?<![\d.])(\d+)\s+\d+\s+R\b")

# (objnum, kind, field2, field3) -- kind 0 free, 1 in-use (offset, gen),
# 2 compressed (container objnum, index).
Entry = tuple[int, int, int, int]


@dataclass(frozen=True)
class UpdateSection:
    """``objects``: every object the update declares, as parsed at its
    offset. ``refs``: the object numbers each one references, read from the
    raw bytes (pypdf drops an indirect stream ``/Length`` once resolved)."""

    trailer: DictionaryObject
    objects: dict[int, PdfObject]
    refs: dict[int, frozenset[int]]
    xref_num: int | None


def _final_startxref(data: bytes) -> tuple[int, int] | None:
    """``(startxref value, position of the keyword)`` of the file's tail."""
    m = _TAIL.search(data)
    return (int(m[1]), m.start()) if m else None


def _raw_refs(data: bytes, start: int, end: int, obj: Any) -> frozenset[int]:
    if isinstance(obj, StreamObject):
        end = data.index(b"stream", start, end)
    return frozenset(int(m[1]) for m in _REF.finditer(data, start, end))


def _read_indirect(data: bytes, offset: int, reader: PdfReader) -> tuple[int, int, Any, int]:
    """``(num, gen, object, end)`` of the ``N G obj ... endobj`` at offset."""
    m = _OBJ_HEADER.match(data, offset)
    if m is None:
        raise ValueError(f"no object header at {offset}")
    pos = _FILLER.match(data, m.end()).end()
    stream = io.BytesIO(data)
    stream.seek(pos)
    obj = read_object(stream, reader)
    pos = _FILLER.match(data, stream.tell()).end()
    if data[pos:pos + 6] != b"endobj":
        raise ValueError(f"object at {offset} not closed by endobj")
    return int(m[1]), int(m[2]), obj, pos + 6


def _read_table(data: bytes, at: int, reader: PdfReader) -> tuple[list[Entry], Any, int]:
    if data[at:at + 4] != b"xref":
        raise ValueError("no xref keyword")
    pos, entries = at + 4, []
    while not data.startswith(b"trailer", _FILLER.match(data, pos).end()):
        head = _SUBSECTION.match(data, pos)
        if head is None:
            raise ValueError("malformed xref subsection")
        pos = head.end()
        for i in range(int(head[2])):
            row = _TABLE_ROW.match(data, pos)
            if row is None:
                raise ValueError("malformed xref row")
            kind = 1 if row[3] == b"n" else 0
            entries.append((int(head[1]) + i, kind, int(row[1]), int(row[2])))
            pos = row.end()
    stream = io.BytesIO(data)
    stream.seek(_FILLER.match(data, pos).end() + len(b"trailer"))
    stream.seek(_FILLER.match(data, stream.tell()).end())
    trailer = read_object(stream, reader)
    return entries, trailer, stream.tell()


def _stream_entries(xref: StreamObject) -> list[Entry]:
    widths = [int(w) for w in xref["/W"]]
    index = [int(i) for i in xref.get("/Index", [0, int(xref["/Size"])])]
    if len(widths) != 3 or len(index) % 2:
        raise ValueError("malformed xref stream /W or /Index")
    raw, row_len, entries = xref.get_data(), sum(widths), []
    numbers = [s + i for s, c in zip(index[::2], index[1::2], strict=True) for i in range(c)]
    if len(raw) != row_len * len(numbers):
        raise ValueError("xref stream length does not match /W x /Index")
    for k, num in enumerate(numbers):
        row, fields, start = raw[k * row_len:(k + 1) * row_len], [], 0
        for w in widths:
            fields.append(int.from_bytes(row[start:start + w], "big"))
            start += w
        kind = fields[0] if widths[0] else 1
        entries.append((num, kind, fields[1], fields[2]))
    return entries


def _trailer_ok(trailer: Any, old_startxref: int) -> bool:
    return (isinstance(trailer, DictionaryObject)
            and int(trailer.get("/Prev", -1)) == old_startxref
            and "/XRefStm" not in trailer and "/Encrypt" not in trailer)


def _declared_objects(
    new: bytes, floor: int, entries: list[Entry], reader: PdfReader,
) -> tuple[dict[int, Any], dict[int, frozenset[int]], list[tuple[int, int]]]:
    objects, spans = {}, []
    refs: dict[int, frozenset[int]] = {}
    for num, kind, f2, f3 in entries:
        if kind == 0 and num == 0:
            continue
        if kind != 1 or f2 < floor or num in objects:
            raise ValueError(f"entry for object {num} is not a fresh in-use object")
        got_num, got_gen, obj, end = _read_indirect(new, f2, reader)
        if (got_num, got_gen) != (num, f3):
            raise ValueError(f"xref entry {num} points at object {got_num}")
        objects[num] = obj
        refs[num] = _raw_refs(new, f2, end, obj)
        spans.append((f2, end))
    return objects, refs, spans


def _covered(data: bytes, start: int, spans: list[tuple[int, int]]) -> bool:
    pos = start
    for s, e in sorted(spans):
        if s < pos or _FILLER.match(data, pos, s).end() != s:
            return False
        pos = e
    return _FILLER.match(data, pos).end() == len(data)


def read_update(old: bytes, new: bytes, reader: PdfReader) -> UpdateSection | None:
    """The one update appended to ``old`` to make ``new``, or ``None``."""
    old_tail, new_tail = _final_startxref(old), _final_startxref(new)
    suffix = new[len(old):]
    if (old_tail is None or new_tail is None or suffix.count(b"%%EOF") != 1
            or suffix.count(b"startxref") != 1 or new_tail[0] < len(old)):
        return None
    at, xref_num = new_tail[0], None
    if new.startswith(b"xref", at):
        entries, trailer, end = _read_table(new, at, reader)
    else:
        xref_num, _, trailer, end = _read_indirect(new, at, reader)
        if not isinstance(trailer, StreamObject) or trailer.get("/Type") != "/XRef":
            return None
        entries = [e for e in _stream_entries(trailer) if e[0] != xref_num]
    if not _trailer_ok(trailer, old_tail[0]):
        return None
    objects, refs, spans = _declared_objects(new, len(old), entries, reader)
    if xref_num is not None:
        objects[xref_num] = trailer
        refs[xref_num] = _raw_refs(new, at, end, trailer)
    if not _covered(new, len(old), [*spans, (at, end), (new_tail[1], len(new))]):
        return None
    return UpdateSection(trailer=trailer, objects=objects, refs=refs, xref_num=xref_num)
