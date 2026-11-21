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
Every caller names the overlay (``load_overlay``); one that cannot is
refused unless its snapshots dir is a standard checkout layout.

Both ``index.json`` files list one entry per sha (``one_per_sha``): the
variant just written or promoted replaces the sha's entry.
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

__all__ = ["OverlayLocationError", "OverlaySource", "VariantMismatchError", "checkout_digest",
           "current_digest",
           "load_overlay", "one_per_sha", "overlay_digest", "resolve_snapshot", "snapshot_name",
           "variant_path"]

_NAME = re.compile(r"^(?P<sha>[^.]+)(?:\.r(?P<digest>[0-9a-f]{12}))?\.json$")


class VariantMismatchError(LookupError):
    """Snapshots exist for the sha, but none was made with the current overlay."""


class OverlayLocationError(VariantMismatchError):
    """No overlay was given and the snapshots dir does not say where it is."""


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


def one_per_sha(files: Sequence[tuple[str, str | None, str]], listed: set[str],
                current: Mapping[str, str]) -> set[str]:
    """Which of ``files`` (``(filename, csv_sha256, fetched_at)``) an index lists:
    one per sha. For a sha with several files (a base and its variants) it is
    ``current[sha]`` (the file just written or promoted), else the one the
    index already ``listed``, else the newest by ``fetched_at``."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for name, sha, fetched_at in files:
        groups.setdefault(sha or name, []).append((name, fetched_at or ""))
    keep = set()
    for sha, group in groups.items():
        names = [n for n, _ in group]
        listed_here = [n for n in names if n in listed]
        if current.get(sha) in names:
            keep.add(current[sha])
        elif len(listed_here) == 1:
            keep.add(listed_here[0])
        else:
            keep.add(max(group, key=lambda g: (g[1], g[0]))[0])
    return keep


# The two snapshot mirrors, relative to the checkout root.
_STANDARD_LAYOUTS = (("data", "manifests", "snapshots"), ("web", "public", "data", "snapshots"))

# An overlay given by the caller: the entries themselves, the overlay file,
# or None -- found from a standard-layout snapshots dir, else refused.
OverlaySource = Overlay | Path | None


def load_overlay(source: OverlaySource, snapshots_dir: Path) -> Overlay:
    """The overlay ``source`` names. ``None`` reads ``data/date_resolutions.json``
    of the checkout a STANDARD-layout ``snapshots_dir`` is in, and raises
    :class:`OverlayLocationError` for any other dir -- never a silent "no
    overlay"."""
    if isinstance(source, Path):
        return load_date_resolutions(source)
    if source is not None:
        return source
    resolved = snapshots_dir.resolve()
    for layout in _STANDARD_LAYOUTS:
        if resolved.parts[-len(layout):] == layout:
            return load_date_resolutions(resolved.parents[len(layout) - 1] / DATE_RESOLUTIONS_FILE)
    raise OverlayLocationError(
        f"{snapshots_dir} is not a checkout's data/manifests/snapshots or "
        f"web/public/data/snapshots, so its {DATE_RESOLUTIONS_FILE} cannot be found; "
        "pass the overlay explicitly (--date-resolutions)")


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


def current_digest(prefix: str, snapshots_dir: Path, overlay: OverlaySource) -> str | None:
    """The current overlay's digest for the sha's snapshots (None when none exist)."""
    found = _candidates(prefix, snapshots_dir)
    if not found:
        return None
    return overlay_digest(load_overlay(overlay, snapshots_dir), found[0][1].get("cards", []))


def checkout_digest(repo_root: Path, prefix: str) -> str | None:
    """The overlay digest of the sha's snapshot in checkout ``repo_root``,
    with its ``data/date_resolutions.json`` named explicitly. Raises
    :class:`VariantMismatchError` unless a snapshot made with it exists
    (or none exists at all)."""
    snapshots = repo_root / "data" / "manifests" / "snapshots"
    overlay = repo_root / DATE_RESOLUTIONS_FILE
    resolve_snapshot(prefix, snapshots, overlay)  # refuses a stale or ambiguous match
    return current_digest(prefix, snapshots, overlay)


def resolve_snapshot(prefix: str, snapshots_dir: Path, overlay: OverlaySource) -> Path | None:
    """The snapshot for ``prefix`` made with the current overlay (None if none exist).

    ``overlay`` is required (``load_overlay``); it is read only when
    snapshots for the sha exist.
    """
    found = _candidates(prefix, snapshots_dir)
    if not found:
        return None
    want = overlay_digest(load_overlay(overlay, snapshots_dir), found[0][1].get("cards", []))
    for path, doc in found:
        named = _NAME.match(path.name)["digest"]
        if doc.get("resolutions_digest") == want and named == (want[:12] if want else None):
            return path
    names = ", ".join(p.name for p, _ in found)
    raise VariantMismatchError(
        f"no snapshot for {prefix[:12]} matches the current {DATE_RESOLUTIONS_FILE} "
        f"(want {snapshot_name(prefix[:12] + '…', want)}; have {names}); regenerate the "
        "snapshot with the current overlay (scripts/poll_snapshot.py)")
