"""Release completeness gate — refuse a release with missing transcripts or A/V bytes.

Nothing else gates a release on audio transcription or on the A/V bytes being
registered: the ``pages.json`` coverage spec is ``require_no_missing=False`` by
design and the poster gate only fires in CI on a pull request. This is the
first target of ``make ship-ready``.

Three independent checks, all reported before exiting:

* **Transcripts** — every AUD card in the manifest needs
  ``<ocr_dir>/<card_id>/pages.jsonl`` with an ``engine: assemblyai`` row, or a
  committed waiver row (``card_id`` + ``reason``) in
  ``data/transcript-waivers.jsonl``. Honoured waivers are printed.
* **A/V bytes** — every VID/AUD card needs a registry row whose ``current_key``
  is ``<card_id>.<ext>`` for an audio/video extension. (A paired PDF's
  ``<card_id>.pdf`` row is not the A/V bytes.)
* **Transcript shape** — no assemblyai sidecar may carry the channel-duplication
  shape: one-word utterances repeated back to back, as when a dual-mono file
  is transcribed as two channels. A waiver excuses a missing transcript, never a corrupt one.

Repo and data root only; no network. Exit 0 clean, 1 on any problem or on an
input that cannot be read (a gate that cannot look must not pass).

Usage::

    python scripts/check_release_completeness.py
    python scripts/check_release_completeness.py --data-root "$PURSUE_DATA_ROOT"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from pursue_index.config.settings import Settings  # noqa: E402
from pursue_index.transcribe.run import looks_channel_duplicated  # noqa: E402

AV_TYPES = ("VID", "AUD")
AV_EXTENSIONS = ("mp4", "m4a", "mp3", "wav", "mov", "webm", "mkv", "aac", "ogg", "flac")
TRANSCRIPT_ENGINE = "assemblyai"


class CompletenessError(Exception):
    """An input the gate needs is missing or unreadable — the run cannot pass."""


@dataclass
class Report:
    """What the three checks found, in manifest order within each list."""

    missing_transcripts: list[str] = field(default_factory=list)
    missing_bytes: list[str] = field(default_factory=list)
    duplicated: list[str] = field(default_factory=list)
    waived: list[tuple[str, str]] = field(default_factory=list)
    checked_aud: int = 0
    checked_av: int = 0

    @property
    def problems(self) -> int:
        return len(self.missing_transcripts) + len(self.missing_bytes) + len(self.duplicated)


def _read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompletenessError(f"cannot read {label} {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CompletenessError(f"{label} {path}:{n} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise CompletenessError(f"{label} {path}:{n} is not a JSON object")
        rows.append(row)
    return rows


def load_manifest_cards(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CompletenessError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CompletenessError(f"manifest {path} is not valid JSON: {exc}") from exc
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list):
        raise CompletenessError(f"manifest {path} has no 'cards' list")
    return [c for c in cards if isinstance(c, dict) and c.get("card_id")]


def load_waivers(path: Path) -> dict[str, str]:
    """``{card_id: reason}``. An absent file is no waivers; a bad row fails closed."""
    if not path.exists():
        return {}
    waivers: dict[str, str] = {}
    for row in _read_jsonl(path, "waivers file"):
        card_id, reason = row.get("card_id"), str(row.get("reason") or "").strip()
        if not card_id or not reason:
            raise CompletenessError(
                f"waivers file {path}: every waiver needs a card_id and a reason: {row}"
            )
        waivers[str(card_id)] = reason
    return waivers


def load_av_keys(registry: Path) -> set[str]:
    """Every ``current_key`` in the registry; rows without one are ignored."""
    rows = _read_jsonl(registry, "registry")
    return {str(r["current_key"]) for r in rows if r.get("current_key")}


def _sidecar_rows(pages_path: Path) -> list[dict[str, Any]] | None:
    """The assemblyai rows of a card's sidecar, or ``None`` when it has none."""
    if not pages_path.exists():
        return None
    try:
        lines = pages_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CompletenessError(f"cannot read sidecar {pages_path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("engine") == TRANSCRIPT_ENGINE:
            rows.append(row)
    return rows or None


def _utterances(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Recover the utterance blocks from sidecar pages.

    ``transcribe.pages`` renders each page as ``"<speaker>: <text>"`` blocks
    separated by a blank line; a block is one run of one speaker's turns.
    """
    out: list[dict[str, object]] = []
    for row in rows:
        for block in str(row.get("text", "")).split("\n\n"):
            _, _, text = block.partition(": ")
            if text.strip():
                out.append({"text": text})
    return out


def check_transcripts(
    aud_ids: list[str], ocr_dir: Path, waivers: dict[str, str], report: Report
) -> None:
    for card_id in aud_ids:
        rows = _sidecar_rows(ocr_dir / card_id / "pages.jsonl")
        if rows is None:
            if card_id in waivers:
                report.waived.append((card_id, waivers[card_id]))
            else:
                report.missing_transcripts.append(card_id)
        elif looks_channel_duplicated(_utterances(rows)):
            report.duplicated.append(card_id)


def check_bytes(av_ids: list[str], keys: set[str], report: Report) -> None:
    for card_id in av_ids:
        if not any(f"{card_id}.{ext}" in keys for ext in AV_EXTENSIONS):
            report.missing_bytes.append(card_id)


def _distinct_ids(cards: list[dict[str, Any]], types: tuple[str, ...]) -> list[str]:
    seen: dict[str, None] = {}
    for card in cards:
        if card.get("asset_type") in types:
            seen.setdefault(str(card["card_id"]), None)
    return list(seen)


def run_checks(manifest: Path, data_root: Path, registry: Path, waivers_path: Path) -> Report:
    if not (data_root.is_dir() and os.access(data_root, os.R_OK | os.X_OK)):
        raise CompletenessError(f"data root {data_root} is not a readable directory")
    cards = load_manifest_cards(manifest)
    waivers = load_waivers(waivers_path)
    keys = load_av_keys(registry)
    aud_ids, av_ids = _distinct_ids(cards, ("AUD",)), _distinct_ids(cards, AV_TYPES)
    report = Report(checked_aud=len(aud_ids), checked_av=len(av_ids))
    check_transcripts(aud_ids, data_root / "ocr", waivers, report)
    check_bytes(av_ids, keys, report)
    return report


def render(report: Report) -> list[str]:
    lines = [f"waived transcript: {cid} — {why}" for cid, why in report.waived]
    lines += [f"missing transcript: {cid}" for cid in report.missing_transcripts]
    lines += [
        f"missing A/V bytes: {cid} (no registry row with current_key {cid}.<ext>)"
        for cid in report.missing_bytes
    ]
    lines += [
        f"channel-duplicated transcript: {cid} (one-word utterances repeated per channel)"
        for cid in report.duplicated
    ]
    counts = (
        f"{report.checked_aud} AUD, {report.checked_av} VID/AUD checked, "
        f"{len(report.waived)} waived"
    )
    if report.problems:
        lines.append(
            f"release completeness: {report.problems} problem(s) — "
            f"{len(report.missing_transcripts)} missing transcript, "
            f"{len(report.missing_bytes)} missing A/V bytes, "
            f"{len(report.duplicated)} channel-duplicated ({counts})"
        )
    else:
        lines.append(f"release completeness: OK ({counts})")
    return lines


def build_parser() -> argparse.ArgumentParser:
    data = REPO_ROOT / "data"
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=data / "manifests" / "latest.json")
    parser.add_argument("--registry", type=Path, default=data / "asset-bytes-registry.jsonl")
    parser.add_argument("--waivers", type=Path, default=data / "transcript-waivers.jsonl")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="root holding ocr/<card_id>/pages.jsonl (default: PURSUE_DATA_ROOT / settings)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_root = args.data_root or Settings().data_root
        report = run_checks(args.manifest, data_root, args.registry, args.waivers)
    except CompletenessError as exc:
        print(f"release completeness: ERROR: {exc}", file=sys.stderr)
        return 1
    print("\n".join(render(report)))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
