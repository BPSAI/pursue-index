"""Which archive a card identifier can be looked for in (spec §6, PV1.5).

An identifier is a name only inside the numbering system that issued it. Two of
the families this pipeline resolves are bare numbers — a Project Blue Book case
number, a NARA National Archives Identifier — and a bare number carries nothing
that says which system it belongs to. The digits ``10073`` are Blue Book case
10073 in the Blue Book collection; in an FBI or CIA release they are that
archive's own numbering, or a batch, or part of a title.

So a numeric identifier is looked for only in the collection that issues it. The
catalogue already records which archive each row came from (the ``agency`` a
row's path is read as), and that is the metadata this scope is decided on: a row
from any other collection is not a candidate, and a row whose collection could
not be read is not one either — "unknown" is not a statement that the row
belongs to the family, and a claim cites a specific artifact by URL.

Structured identifiers need no such scope, and deliberately do not get one: a
file number like ``62-HQ-83894`` or a ``CIA-RDP…`` document ID states its own
agency and series inside the value, so it means the same document wherever an
archive writes it — including in mirrors filed under no recognised collection.

Pure lookup. No I/O.
"""

from __future__ import annotations

from pursue_index.identifiers import Identifier, IdentifierKind
from pursue_index.source_index import SourceEntry

__all__ = [
    "COLLECTIONS_BY_KIND",
    "entry_in_identifier_collection",
]

#: The archives that issue each bare-number identifier family, as the catalogue
#: names them (:func:`~pursue_index.source_index.infer_agency` slugs). A family
#: absent from this mapping carries its own scope in its value and is searched
#: across the whole catalogue.
COLLECTIONS_BY_KIND: dict[IdentifierKind, frozenset[str]] = {
    IdentifierKind.BLUE_BOOK_CASE: frozenset({"project_blue_book"}),
    IdentifierKind.NAID: frozenset({"nara"}),
}


def entry_in_identifier_collection(ident: Identifier, entry: SourceEntry) -> bool:
    """True iff ``entry`` sits in an archive that could hold ``ident``.

    A family with no collection scope is at home anywhere in the catalogue; a
    bare-number family is at home only in the archive that issues its numbers.
    """
    collections = COLLECTIONS_BY_KIND.get(ident.kind)
    if collections is None:
        return True
    return entry.agency in collections
