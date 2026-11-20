"""Snapshot identity under the manual date-resolution overlay.

Snapshots are content-addressed by ``csv_sha256`` and never rewritten. An
overlay entry (``date_resolutions``) changes what a snapshot holds, so the
entries that APPLY to a CSV are part of its identity: an entry applies when
it names a ``(card_id, field)`` whose upstream value has a 2-digit year
(``year_normalize.upstream_value``). That set is the same whether it is read
from the parsed CSV or from any snapshot of it, so a reader can compute it
without re-running the normalization.

* No applicable entry: digest ``None``; names are exactly as before
  (``<csv_sha>.json``, ``tranche-diff-<sha12>.json``, ``<sha12>.json``).
* Otherwise: ``resolutions_digest`` is the sha256 of the applicable entries
  (``[card_id, field, value, curator, approved_at]``, sorted, canonical
  JSON); every output takes the suffix ``.r<digest12>`` before ``.json``
  and the snapshot records the full digest.

``resolve_snapshot`` picks the snapshot whose recorded digest is the
current overlay's; when snapshots exist for the sha but none matches it
raises :class:`VariantMismatchError` -- it never falls back to the base.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pursue_index.scrape.date_resolutions import (
    DATE_RESOLUTIONS_FILE,
    Overlay,
    load_date_resolutions,
)
from pursue_index.scrape.year_normalize import DATE_FIELDS, upstream_value

__all__ = ["VariantMismatchError", "current_digest", "overlay_digest", "overlay_for_snapshots",
           "resolve_snapshot", "snapshot_name", "variant_path"]

_NAME = re.compile(r"^(?P<sha>[^.]+)(?:\.r(?P<digest>[0-9a-f]{12}))?\.json$")


class VariantMismatchError(LookupError):
    """Snapshots exist for the sha, but none was made with the current overlay."""


def overlay_digest(overlay: Overlay, cards: Sequence[Mapping[str, Any]]) -> str | None:
    """The digest of the overlay entries that apply to ``cards``, or None."""
    targets = {(c.get("card_id"), f) for c in cards for f in DATE_FIELDS
               if upstream_value(c, f) is not None}
    rows = sorted([cid, fld, e.get("value"), e.get("curator"), e.get("approved_at")]
                  for (cid, fld), e in overlay.items() if (cid, fld) in targets)
    if not rows:
        return None
    blob = json.dumps(rows, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _suffix(digest: str | None) -> str:
    return f".r{digest[:12]}" if digest else ""


def snapshot_name(sha: str, digest: str | None) -> str:
    """``<sha>.json``, or ``<sha>.r<digest12>.json`` under an applicable overlay."""
    return f"{sha}{_suffix(digest)}.json"


def variant_path(path: Path, digest: str | None) -> Path:
    """``path`` with ``.r<digest12>`` before its suffix (unchanged without a digest)."""
    return path.with_name(f"{path.stem}{_suffix(digest)}{path.suffix}") if digest else path


def overlay_for_snapshots(snapshots_dir: Path) -> Overlay:
    """The overlay of the checkout ``snapshots_dir`` (``data/manifests/snapshots``) is in."""
    root = snapshots_dir.resolve().parent.parent.parent
    return load_date_resolutions(root / DATE_RESOLUTIONS_FILE)


def _candidates(prefix: str, snapshots_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not snapshots_dir.is_dir():
        return []
    out = []
    for path in sorted(snapshots_dir.glob(f"{prefix}*.json")):
        if path.name != "index.json" and _NAME.match(path.name):
            out.append((path, _read(path)))
    shas = {doc.get("csv_sha256") for _, doc in out}
    if len(shas) > 1:
        raise VariantMismatchError(f"sha prefix {prefix} matches {len(shas)} different snapshots")
    return out


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def current_digest(prefix: str, snapshots_dir: Path, overlay: Overlay | None = None) -> str | None:
    """The current overlay's digest for the sha's snapshots (None when none exist)."""
    found = _candidates(prefix, snapshots_dir)
    if not found:
        return None
    overlay = overlay_for_snapshots(snapshots_dir) if overlay is None else overlay
    return overlay_digest(overlay, found[0][1].get("cards", []))


def resolve_snapshot(prefix: str, snapshots_dir: Path,
                     overlay: Overlay | None = None) -> Path | None:
    """The snapshot for ``prefix`` made with the current overlay (None if none exist).

    ``overlay`` defaults to the checkout's ``data/date_resolutions.json``.
    """
    found = _candidates(prefix, snapshots_dir)
    if not found:
        return None
    overlay = overlay_for_snapshots(snapshots_dir) if overlay is None else overlay
    want = overlay_digest(overlay, found[0][1].get("cards", []))
    for path, doc in found:
        named = _NAME.match(path.name)["digest"]
        if doc.get("resolutions_digest") == want and named == (want[:12] if want else None):
            return path
    names = ", ".join(p.name for p, _ in found)
    raise VariantMismatchError(
        f"no snapshot for {prefix[:12]} matches the current {DATE_RESOLUTIONS_FILE} "
        f"(want {snapshot_name(prefix[:12] + '…', want)}; have {names}); regenerate the "
        "snapshot with the current overlay (scripts/poll_snapshot.py)")
