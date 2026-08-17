"""Reading and rendering corpus text as the characters it actually contains.

Every value this pipeline handles — a card title, a filename, a description, a
sitemap ``<loc>`` — is text the government wrote, carried through a CSV and a
JSON manifest. Some of those bytes are *control* characters: the C0 range
(``U+0000`` to ``U+001F``, which includes tab, carriage return and line feed),
``DEL``, and the C1 range (``U+0080`` to ``U+009F``). They stand for no character a
reader would see on the page.

Two places need them removed, for the same reason and by the same rule:

* **Deciding what a value is.** A scheme token split across a tab is still the
  scheme it names, so the value is read with the controls removed before any
  rule is applied to it (see
  :func:`~pursue_index.provenance.is_citable_prior_source`).
* **Rendering a value to a terminal.** A console interprets ``ESC`` and its
  neighbours as instructions — cursor moves, colour changes, screen clears —
  rather than printing them. ``rich``'s ``escape()`` and ``markup=False``
  settle ``rich``'s own markup language and nothing else, so corpus text is
  passed through :func:`console_text` as well: what the terminal shows is then
  the characters the government wrote.

Pure text. No I/O.
"""

from __future__ import annotations

__all__ = [
    "console_text",
    "strip_control_chars",
]


def _is_control(char: str) -> bool:
    """True for a character that stands for no visible character of its own."""
    code = ord(char)
    return code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F


def strip_control_chars(value: str) -> str:
    """Return ``value`` without its C0, ``DEL`` and C1 characters.

    Removal (rather than substitution) keeps the result the same length as the
    text a reader sees, so a value that carries none is returned unchanged and
    comparisons against it are unaffected.
    """
    return "".join(char for char in value if not _is_control(char))


def console_text(value: object) -> str:
    """Render a corpus-derived value as literal text for a console sink.

    Titles, filenames, identifiers and URLs are data, so a console prints the
    characters they hold and nothing more. This is the last step before
    interpolation, and it composes with — rather than replaces — ``rich``'s own
    ``escape()`` / ``markup=False``: those settle markup, this settles the
    control bytes underneath it.
    """
    return strip_control_chars(str(value))
