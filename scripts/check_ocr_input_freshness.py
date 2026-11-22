"""OCR-input freshness gate: a card's OCR must have read the registry's latest PDF bytes.

For every published PDF card, ``<data_root>/ocr/<card_id>/meta.json``
``pdf_sha256`` must equal the latest ``.pdf`` row ``byte_sha256`` in the
asset-bytes registry, or a ``resave-content-verified`` row in
``data/byte-change-dispositions.jsonl`` must cover exactly that pair.

A mismatch exits 1 and lists the card, both shas and the disposition status.
A missing or unreadable registry and an invalid card id also fail closed. A
published PDF card with no registry PDF row has nothing to compare: it is listed
and counted (``unregistered``) and recorded, never silently skipped, but does not
fail the gate.

A published PDF card that is still without a registry PDF row more than
``--unregistered-days`` (default 3) days after its manifest ``release_date`` (the
publication date) is ``unregistered-stale``: counted, listed with the date used, and
failing above ``--max-unregistered-stale N`` exactly as ``unverifiable`` does. One with
no parseable ``release_date`` cannot be aged, so it is ``unregistered-undated``: listed,
recorded, and counted against that same ceiling, never skipped.

A card with no ``meta.json`` or no recorded ``pdf_sha256`` has no input sha to
compare, and the scoping rule never re-OCRs it. It is reported as
``unverifiable provenance`` (warned, exit code unaffected) and its count and card
list go in the release record written with ``--record``. ``--max-unverifiable N``
sets a ceiling on that class: above N the gate fails (the ``make`` target passes one);
at or below it the class stays warn-only. Repo and data root only; no network.

Usage::

    python scripts/check_ocr_input_freshness.py [--data-root DIR] [--record FILE]
        [--max-unverifiable N] [--unregistered-days N] [--max-unregistered-stale N]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Code is loaded from where this script lives, never from the data root
# (cwd / PURSUE_REPO_ROOT), so this runs before any pursue_index import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import json
from datetime import date, timedelta

from _freshness_manifest import FreshnessError, _manifest_cards
from _freshness_result import UNREGISTERED_STALE_DAYS, Result

from pursue_index.byte_dispositions import (
    ByteDispositionError,
    Disposition,
    covers,
    load_byte_change_dispositions,
)
from pursue_index.config.settings import Settings
from pursue_index.ingest_scope import load_registry_sha_map
from pursue_index.paths import repo_root

REPO_ROOT = repo_root()


def check(
    manifest: Path,
    registry: Path,
    dispositions: dict[tuple[str, str], Disposition],
    data_root: Path,
    today: date | None = None,
    unregistered_days: int = UNREGISTERED_STALE_DAYS,
) -> Result:
    """Classify every published PDF card; see the module docstring."""
    if not (data_root / "ocr").is_dir():
        raise FreshnessError(
            "PURSUE_DATA_ROOT must point at the data root containing ocr/ "
            f"(looked in {data_root}, which has no ocr/ directory)"
        )
    if not registry.is_file():
        raise FreshnessError(f"registry {registry} is missing or not a file")
    try:
        registry_sha = load_registry_sha_map(registry)
    except (OSError, ValueError) as exc:
        raise FreshnessError(f"cannot read registry {registry}: {exc}") from exc
    res = Result(unregistered_days=unregistered_days)
    cutoff = (today or date.today()) - timedelta(days=unregistered_days)
    for card_id, is_pdf, released in _manifest_cards(manifest):
        new = registry_sha.get(card_id)
        if new is None:
            if is_pdf:
                res.unregistered.append(card_id)
                if released is None:
                    res.unregistered_undated.append(card_id)
                elif released < cutoff:
                    res.unregistered_stale.append((card_id, released))
            continue
        res.checked += 1
        meta = data_root / "ocr" / card_id / "meta.json"
        if not meta.is_file():
            res.unverifiable.append((card_id, "no meta.json"))
            continue
        try:
            old = json.loads(meta.read_text(encoding="utf-8")).get("pdf_sha256")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise FreshnessError(f"cannot read {meta}: {exc}") from exc
        if not old:
            res.unverifiable.append((card_id, "no pdf_sha256"))
        elif old == new:
            continue
        elif covers(dispositions, card_id, old, new):
            res.covered.append(f"{card_id} ocr={old} registry={new} (covered by disposition)")
        else:
            res.stale.append(f"{card_id} ocr={old} registry={new} (no disposition covers this pair)")
    return res


def _non_negative(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def _report_lines(res: Result) -> list[str]:
    """Every report line for a finished check, ending with the verdict."""
    lines = [f"stale OCR input: {s}" for s in res.stale]
    lines += [f"covered: {c}" for c in res.covered]
    lines += [f"PDF card with no registry PDF row: {c}" for c in res.unregistered]
    lines += [
        f"unregistered-stale: {c} (released {d.isoformat()}, from the manifest release_date; "
        f"no registry row after more than {res.unregistered_days} days)"
        for c, d in res.unregistered_stale
    ]
    lines += [
        f"unregistered-undated: {c} (no parseable release_date, so it cannot be aged; "
        "no registry row)"
        for c in res.unregistered_undated
    ]
    lines += [f"unverifiable provenance: {c} ({why})" for c, why in res.unverifiable]
    counts = (
        f"{res.checked} PDF cards checked, ok {res.checked - len(res.stale) - len(res.covered) - len(res.unverifiable)}, "
        f"{len(res.stale)} stale, {len(res.covered)} covered, "
        f"unregistered: {len(res.unregistered)}, "
        f"unregistered-stale: {len(res.unregistered_stale)}, "
        f"unregistered-undated: {len(res.unregistered_undated)}, unverifiable provenance: {len(res.unverifiable)}"
    )
    if res.over_ceiling:
        lines.append(
            f"unverifiable provenance count {len(res.unverifiable)} exceeds the ceiling "
            f"{res.max_unverifiable} (--max-unverifiable)"
        )
    if res.over_stale_ceiling:
        lines.append(
            f"unregistered-stale + undated count "
            f"{len(res.unregistered_stale) + len(res.unregistered_undated)} exceeds the ceiling "
            f"{res.max_unregistered_stale} (--max-unregistered-stale)"
        )
    lines.append(f"ocr input freshness: {'FAILED' if res.failed else 'OK'} ({counts})")
    return lines


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    """Run the gate. ``today`` is a test seam for the clock; it is not a command-line option."""
    data = REPO_ROOT / "data"
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=data / "manifests" / "latest.json")
    parser.add_argument("--registry", type=Path, default=data / "asset-bytes-registry.jsonl")
    parser.add_argument(
        "--dispositions", type=Path, default=data / "byte-change-dispositions.jsonl"
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--record", type=Path, default=None,
        help="write the release record (counts, unverifiable cards) to this JSON file",
    )
    parser.add_argument(
        "--max-unverifiable", type=_non_negative, default=None, metavar="N",
        help="fail when more than N cards have unverifiable provenance (default: warn only)",
    )
    parser.add_argument(
        "--unregistered-days", type=_non_negative, default=UNREGISTERED_STALE_DAYS, metavar="N",
        help="days after a card's release_date before a missing registry row is stale (default 3)",
    )
    parser.add_argument(
        "--max-unregistered-stale", type=_non_negative, default=None, metavar="N",
        help="fail when more than N PDF cards are unregistered-stale or unregistered-undated "
        "(default: warn only)",
    )
    args = parser.parse_args(argv)
    try:
        data_root = args.data_root or Settings().data_root
        dispositions = load_byte_change_dispositions(args.dispositions)
        res = check(
            args.manifest, args.registry, dispositions, data_root,
            today=today, unregistered_days=args.unregistered_days,
        )
        res.max_unverifiable = args.max_unverifiable
        res.max_unregistered_stale = args.max_unregistered_stale
        if args.record is not None:
            args.record.write_text(
                json.dumps(res.record(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    except (FreshnessError, ByteDispositionError, OSError) as exc:
        print(f"ocr input freshness: ERROR: {exc}", file=sys.stderr)
        return 1
    lines = _report_lines(res)
    print("\n".join(lines))
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
