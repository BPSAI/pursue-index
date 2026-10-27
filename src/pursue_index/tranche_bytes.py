"""Byte-level evidence for a Class C candidate: metadata-only re-save or not.

``classify_bytes(old_path, new_path)`` answers one question about two
versions of a PDF: is the new file the old file plus ONE incremental update
that touches nothing but document metadata? (The D042 case: war.gov
re-saved a PDF, appending an update that rewrote only the Info dict, the
XMP stream, the catalog's ``/Metadata`` pointer and the xref stream; every
image and text byte was untouched.)

Verdicts:

  * ``"content-changed"`` when the new bytes do not start with the old
    bytes, when the appended bytes are not exactly one clean incremental
    update (see ``pursue_index.pdf_update``), or when that update changes
    any object outside the metadata set below. Anything this module cannot
    parse confidently is also ``content-changed`` -- the same bias toward
    the safer verdict that ``tranche.find_title_continuity`` documents for
    Class C: a false ``content-changed`` costs an operator review, a false
    ``metadata-only`` would silently alias tampered content.
  * ``"metadata-only"`` when every object the update declares is one of:
      - the trailer's ``/Info`` dictionary;
      - an XMP stream (``/Type /Metadata /Subtype /XML``);
      - the update's own xref stream;
      - the trailer's ``/Root`` catalog, if it differs from the old catalog
        only in ``/Metadata`` and that pointer resolves to an XMP stream;
      - a brand-new leaf object (number/string/name) referenced from one of
        the above -- e.g. an XMP stream's indirect ``/Length``.
    An object number that already existed in the old file may only be
    rewritten in the SAME role it had there (an old content stream cannot
    be re-used as the "XMP stream"), and the trailer may not switch
    ``/Root`` to a different pre-existing object.

Pure: reads only the two files; ``FileNotFoundError`` propagates (callers
map it to "no verdict"). Standard library + pypdf only, both already in
``requirements-poll.txt``.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    DictionaryObject,
    FloatObject,
    IndirectObject,
    NameObject,
    NullObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from pursue_index.classify_isolated import run_worker
from pursue_index.pdf_crosscheck import CrossCheckError, crosscheck
from pursue_index.pdf_limits import (
    Budget,
    LimitExceededError,
    capped_pypdf,
    check_file_size,
    check_update_count,
    read_capped,
)
from pursue_index.pdf_refs import referenced_elsewhere
from pursue_index.pdf_update import UpdateSection, read_update

__all__ = ["CONTENT_CHANGED", "METADATA_ONLY", "Verdict", "classify_bytes"]

Verdict = Literal["metadata-only", "content-changed"]
METADATA_ONLY: Verdict = "metadata-only"
CONTENT_CHANGED: Verdict = "content-changed"

_LOG = logging.getLogger(__name__)
_LEAVES = (BooleanObject, ByteStringObject, FloatObject, NameObject, NullObject,
           NumberObject, TextStringObject)


def classify_bytes(
    old_path: Path, new_path: Path, *, isolated: bool = True,
    old_sha256: str | None = None, new_sha256: str | None = None,
) -> Literal["metadata-only", "content-changed"]:
    """``metadata-only`` iff ``new_path`` is ``old_path`` plus one metadata-only
    incremental update that ALSO passes the independent cross-check
    (``pdf_crosscheck``); ``content-changed`` otherwise (module docstring).

    ``isolated`` (the default) runs the work in a resource-limited worker
    (``classify_isolated``); ``False`` runs it in-process (tests, the worker).
    ``old_sha256``/``new_sha256`` make the reading side re-verify each file's
    bytes (the worker does, so a swap after the parent's check is refused).
    """
    if isolated:
        old_path, new_path = Path(old_path), Path(new_path)
        try:
            for path in (old_path, new_path):
                check_file_size(path)  # FileNotFoundError / size cap before spawning
        except LimitExceededError as exc:
            _LOG.warning("classify fail-safe: %s", exc)
            return CONTENT_CHANGED
        return run_worker(old_path, new_path, old_sha256, new_sha256) or CONTENT_CHANGED
    return _classify_in_process(Path(old_path), Path(new_path), old_sha256, new_sha256)


def _classify_in_process(
    old_path: Path, new_path: Path, old_sha256: str | None = None, new_sha256: str | None = None,
) -> Verdict:
    try:
        old = read_capped(old_path, old_sha256)
        new = read_capped(new_path, new_sha256)
        if len(new) <= len(old) or not new.startswith(old):
            return CONTENT_CHANGED
        budget = Budget()
        # ``new`` carries the whole old file as its prefix (checked above), so
        # counting ``startxref`` in ``new`` also bounds the old file's /Prev
        # chain that pypdf walks -- never call this with the suffix alone.
        if check_update_count(new) < old.count(b"startxref"):
            return CONTENT_CHANGED
        with capped_pypdf():
            if not _is_metadata_only(old, new, budget):
                return CONTENT_CHANGED
            crosscheck(old, new, budget)
        return METADATA_ONLY
    except LimitExceededError as exc:
        _LOG.warning("classify_bytes fail-safe %s (%s): %s", CONTENT_CHANGED, exc.reason, exc)
        return CONTENT_CHANGED
    except CrossCheckError as exc:
        _LOG.warning("classify_bytes fail-safe %s (crosscheck %s): %s",
                     CONTENT_CHANGED, exc.signal, exc)
        return CONTENT_CHANGED
    except (FileNotFoundError, KeyboardInterrupt):
        raise
    except Exception:  # noqa: BLE001 -- unparseable means "cannot vouch for it"
        return CONTENT_CHANGED


def _ref_num(d: DictionaryObject, key: str) -> int | None:
    value = d.raw_get(key) if key in d else None
    return value.idnum if isinstance(value, IndirectObject) else None


def _canon(v: Any) -> Any:
    """A reader-independent comparable form (pypdf refs compare by reader)."""
    if isinstance(v, IndirectObject):
        return ("R", v.idnum, v.generation)
    if isinstance(v, DictionaryObject):
        return ("D", tuple(sorted((str(k), _canon(x)) for k, x in v.items())))
    if isinstance(v, ArrayObject):
        return ("A", tuple(_canon(x) for x in v))
    return (type(v).__name__, bytes(v) if isinstance(v, bytes) else str(v))


def _role(num: int, obj: Any, trailer: DictionaryObject, xref_num: int | None) -> str | None:
    if isinstance(obj, StreamObject):
        if num == xref_num and obj.get("/Type") == "/XRef":
            return "xref"
        if obj.get("/Type") == "/Metadata" and obj.get("/Subtype") == "/XML":
            return "metadata"
        return None
    if isinstance(obj, DictionaryObject):
        if num == _ref_num(trailer, "/Info"):
            return "info"
        if num == _ref_num(trailer, "/Root") and obj.get("/Type") == "/Catalog":
            return "catalog"
    return None


def _old_numbers(reader: PdfReader) -> set[int]:
    nums = {n for table in reader.xref.values() for n in table}
    return nums | set(reader.xref_objStm)


def _old_role(num: int, old: PdfReader) -> str | None:
    obj = old.get_object(num)
    is_xref = isinstance(obj, StreamObject) and obj.get("/Type") == "/XRef"
    return _role(num, obj, old.trailer, num if is_xref else None)


def _catalog_ok(catalog: DictionaryObject, old: PdfReader, new: PdfReader) -> bool:
    def strip(d: DictionaryObject) -> Any:
        return _canon(DictionaryObject({k: v for k, v in d.items() if k != "/Metadata"}))

    old_catalog = old.trailer["/Root"].get_object()
    if strip(catalog) != strip(old_catalog):
        return False
    if "/Metadata" not in catalog:
        return True
    target = catalog.raw_get("/Metadata")
    return (isinstance(target, IndirectObject)
            and _role(target.idnum, new.get_object(target), new.trailer, None) == "metadata")


def _is_metadata_only(old_bytes: bytes, new_bytes: bytes, budget: Budget) -> bool:
    budget.check()
    old = PdfReader(io.BytesIO(old_bytes))
    budget.check()
    new = PdfReader(io.BytesIO(new_bytes))
    budget.check()
    section = read_update(old_bytes, new_bytes, new, budget)
    if section is None or not _root_kept(section, old):
        return False
    old_nums = _old_numbers(old)
    roles = {n: _role(n, o, section.trailer, section.xref_num)
             for n, o in section.objects.items()}
    if any(n in old_nums and r is not None and _old_role(n, old) != r for n, r in roles.items()):
        return False
    if any(r == "catalog" and not _catalog_ok(section.objects[n], old, new)
           for n, r in roles.items()):
        return False
    if any(r == "metadata" and referenced_elsewhere(n, new, budget) for n, r in roles.items()):
        return False  # a metadata-typed stream used as content is content
    referenced = set().union(*(section.refs[n] for n, r in roles.items() if r))
    return all(r is not None or _is_aux_leaf(n, section, old_nums, referenced)
               for n, r in roles.items())


def _root_kept(section: UpdateSection, old: PdfReader) -> bool:
    """``/Root`` stays the old catalog's number or names a re-written catalog."""
    root = _ref_num(section.trailer, "/Root")
    return root is not None and (
        root == _ref_num(old.trailer, "/Root") or root in section.objects
    )


def _is_aux_leaf(num: int, section: UpdateSection, old_nums: set[int],
                 referenced: set[int]) -> bool:
    return (num not in old_nums and num in referenced
            and isinstance(section.objects[num], _LEAVES))
