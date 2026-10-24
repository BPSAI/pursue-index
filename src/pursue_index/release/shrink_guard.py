"""Shrink guard shared by the derivative builders.

``scripts/build_search_data.py`` and ``scripts/build_embed_data.py`` regenerate
their committed payloads (``pages.json``, ``embed_index.json``) wholesale from
the data root. On a root that holds OCR for only the new cards the rebuild
silently drops every other card's text and vectors, and nothing downstream
notices. Each builder therefore checks its result against the payload already
on disk and refuses (exit 1, listing the ids) when either

* the rebuilt set covers fewer ``card_id``s than the committed one, or
* a manifest card that must carry text has neither OCR pages nor a transcript
  on the data root.

An operator who really means to shrink passes ``--allow-shrink --reason ...``;
that is recorded as an audited exception in ``data/audit-log.jsonl``. An
approved rename removes its old ``card_id`` by design, so a shrunk id whose
``data/card-aliases.json`` row points at a ``card_id`` present in the rebuild
is reported (``renamed: <old> -> <new>``) rather than refused.

Only PDF cards are *required* to carry text. A VID has no transcript pipeline
and an AUD/IMG card awaiting transcription or a vision pass is a backlog, not
a loss: requiring text of them would fail the committed tree as it stands. A
loss on any card type is still caught by the shrink comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pursue_index.ingest_scope import load_aliases as _load_alias_rows
from pursue_index.release.chunked_asset import asset_exists, read_asset_json

TEXT_REQUIRED_TYPES = frozenset({"PDF"})


def add_shrink_args(parser: argparse.ArgumentParser, payload: str) -> None:
    """The ``--allow-shrink`` / ``--reason`` pair, identical on both builders."""
    parser.add_argument(
        "--allow-shrink", action="store_true",
        help=f"Permit a rebuild that covers fewer cards than the committed "
        f"{payload}. Requires --reason; recorded in data/audit-log.jsonl.",
    )
    parser.add_argument(
        "--reason", default=None,
        help="Why the corpus may shrink (audited). Used with --allow-shrink.",
    )


def shrink_reason(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> str | None:
    """The audited reason if shrinking was requested; usage error without one."""
    if not args.allow_shrink:
        return None
    if not (args.reason or "").strip():
        parser.error("--allow-shrink requires --reason")
    return str(args.reason)


def _warn_no_baseline(path: Path) -> None:
    print(
        f"warning: no committed {path.name} at {path}; "
        "skipping the shrink comparison.",
        file=sys.stderr,
    )


def committed_pages_card_ids(path: Path) -> set[str] | None:
    """``card_id``s in a committed ``pages.json``; ``None`` (warned) if absent."""
    if not asset_exists(path):
        _warn_no_baseline(path)
        return None
    return {str(d["card_id"]) for d in read_asset_json(path)}


def committed_embed_card_ids(path: Path) -> set[str] | None:
    """``card_id``s in a committed ``embed_index.json``; ``None`` (warned) if absent."""
    if not asset_exists(path):
        _warn_no_baseline(path)
        return None
    pages = read_asset_json(path)["pages"]
    return {str(row[0]) for row in pages}


def find_shrink(committed: set[str] | None, rebuilt: set[str]) -> list[str]:
    """Committed ``card_id``s the rebuild no longer covers, sorted."""
    return sorted(committed - rebuilt) if committed else []


def load_alias_map(aliases_path: Path | None) -> dict[str, str]:
    """Resolved ``old_card_id -> new_card_id`` map from ``card-aliases.json``.

    Later rows win per ``old_card_id``; ``method: operator_revoke`` tombstones
    the mapping. Mirrors the worker's resolution rule (see
    ``tests/integration/test_alias_destinations.py``). ``None`` or an absent
    path is an empty map, not an error.
    """
    if aliases_path is None:
        return {}
    out: dict[str, str] = {}
    for row in _load_alias_rows(aliases_path):
        old_id, new_id = row.get("old_card_id"), row.get("new_card_id")
        if not (old_id and new_id):
            continue
        if row.get("method") == "operator_revoke":
            out.pop(old_id, None)
            continue
        out[old_id] = new_id
    return out


def resolve_renames(
    shrunk: list[str], rebuilt: set[str], aliases: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Split ``shrunk`` into ids an approved rename accounts for and ids
    still missing.

    An id only counts as renamed when its alias target is present in
    ``rebuilt`` — otherwise the rename did not carry text and the id stays
    missing.
    """
    renamed: list[str] = []
    missing: list[str] = []
    for old_id in shrunk:
        new_id = aliases.get(old_id)
        if new_id is not None and new_id in rebuilt:
            renamed.append(f"{old_id} -> {new_id}")
        else:
            missing.append(old_id)
    return renamed, missing


def find_renamed_and_missing(
    committed: set[str] | None, rebuilt: set[str], aliases_path: Path | None
) -> tuple[list[str], list[str]]:
    """``find_shrink`` + ``resolve_renames`` in one call for the builders."""
    aliases = load_alias_map(aliases_path)
    return resolve_renames(find_shrink(committed, rebuilt), rebuilt, aliases)


def ocr_dir_error(ocr_dir: Path) -> str | None:
    """Why an existing ``ocr_dir`` cannot be listed, else ``None``.

    An absent dir is not an error here: it is an empty root, and the shrink and
    coverage rules already refuse a build that an empty root would shrink.
    """
    try:
        if ocr_dir.exists():
            with os.scandir(ocr_dir):
                pass
    except OSError as exc:
        return f"{ocr_dir}: {exc.strerror or exc}"
    return None


def ocr_covered_ids(ocr_dir: Path) -> set[str]:
    """Cards holding readable pages on the data root.

    A transcript is written to the same ``ocr/<card_id>/{pages.jsonl,
    meta.json}`` path OCR uses, so this one walk covers OCR and transcripts.
    """
    covered: set[str] = set()
    if not ocr_dir.exists():
        return covered
    for card_dir in ocr_dir.iterdir():
        meta, pages = card_dir / "meta.json", card_dir / "pages.jsonl"
        if not (card_dir.is_dir() and meta.exists() and pages.exists()):
            continue
        if json.loads(meta.read_text(encoding="utf-8")).get("status") == "ok":
            covered.add(card_dir.name)
    return covered


def find_uncovered(
    manifest_cards: Iterable[dict[str, Any]], covered: set[str]
) -> list[str]:
    """Manifest cards that must carry text but have none in ``covered``."""
    return sorted(
        {
            str(c["card_id"])
            for c in manifest_cards
            if c.get("asset_type") in TEXT_REQUIRED_TYPES
            and str(c["card_id"]) not in covered
        }
    )


def _record_exception(
    script: str,
    shrunk: list[str],
    uncovered: list[str],
    reason: str,
    audit_log: Path,
) -> None:
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "event": "allow_shrink",
        "script": script,
        "reason": reason,
        "shrunk": shrunk,
        "uncovered": uncovered,
        "at": datetime.now(UTC).isoformat(),
    }
    with audit_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def enforce(
    script: str,
    shrunk: list[str],
    uncovered: list[str],
    *,
    allow_reason: str | None,
    audit_log: Path,
    renamed: list[str] | None = None,
) -> int:
    """Exit code for the findings: 0 if clean or explicitly allowed, else 1.

    Prints every offending id to stderr. A blank reason is not an exception —
    the audit row is the only record of why the corpus was allowed to shrink.
    ``renamed`` (ids an approved rename already accounts for) is reported on
    its own stdout line regardless of the outcome.
    """
    if renamed:
        print(f"renamed: {', '.join(renamed)}")
    if not shrunk and not uncovered:
        return 0
    reason = (allow_reason or "").strip()
    if reason:
        _record_exception(script, shrunk, uncovered, reason, audit_log)
        print(
            f"{script}: shrink allowed ({reason}); audited in {audit_log}",
            file=sys.stderr,
        )
        return 0
    if shrunk:
        print(
            f"{script}: REFUSED — rebuild covers {len(shrunk)} fewer card(s) "
            f"than the committed payload: {', '.join(shrunk)}",
            file=sys.stderr,
        )
    if uncovered:
        print(
            f"{script}: REFUSED — {len(uncovered)} manifest card(s) have "
            f"neither OCR pages nor a transcript on the data root: "
            f"{', '.join(uncovered)}",
            file=sys.stderr,
        )
    print(
        f"{script}: fix the data root, or pass --allow-shrink --reason '<why>' "
        "to record an audited exception.",
        file=sys.stderr,
    )
    return 1
