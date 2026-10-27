"""Record a stale-edge observation as a small note, never as CSV bytes.

Stale-edge CSV bytes used to be committed, which let them pile up without
limit. A note is one JSON file per sha under ``data/stale-edge-notes/``
(sha, size, ``Last-Modified``, fetch time; at most ``MAX_NOTE_BYTES``), and the
directory is capped at ``MAX_NOTES`` entries -- the oldest are pruned here,
not in the workflow.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from _poll_gh_io import HTTP_DATE_CHARS

MAX_NOTE_BYTES = 2 * 1024
MAX_NOTES = 200
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_HEADER = 64


def _clean_header(value: str | None) -> str | None:
    if not value:
        return None
    return "".join(ch for ch in value if ch in HTTP_DATE_CHARS)[:_MAX_HEADER] or None


def _prune(notes_dir: Path) -> None:
    def key(path: Path) -> tuple[str, str]:
        try:
            return (str(json.loads(path.read_text(encoding="utf-8")).get("fetched_at", "")), path.name)
        except (OSError, ValueError, AttributeError):
            return ("", path.name)

    notes = sorted(notes_dir.glob("*.json"), key=key)
    for old in notes[: max(0, len(notes) - MAX_NOTES)]:
        old.unlink()


def write_note(
    notes_dir: Path, sha: str, last_modified: str | None, csv_dir: Path, *, now: str | None = None,
) -> Path:
    """Write (once) the note for ``sha``, then prune the directory to the cap."""
    if not _SHA256_HEX.fullmatch(sha):
        raise ValueError("malformed sha")
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"{sha}.json"
    if not path.exists():
        csv = csv_dir / f"{sha}.csv"
        note = {
            "sha256": sha,
            "size": csv.stat().st_size if csv.is_file() else None,
            "last_modified": _clean_header(last_modified),
            "fetched_at": now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        path.write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8")
    _prune(notes_dir)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("--last-modified", default=None)
    parser.add_argument("--notes-dir", type=Path, default=Path("data/stale-edge-notes"))
    parser.add_argument("--csv-dir", type=Path, default=Path("data/raw/csv"))
    args = parser.parse_args(argv)
    try:
        path = write_note(args.notes_dir, args.sha, args.last_modified, args.csv_dir)
    except ValueError as exc:
        print(f"skip: {exc}")
        return 1
    print(f"note: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
