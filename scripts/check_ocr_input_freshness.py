"""OCR-input freshness gate: a card's OCR must have read the registry's latest PDF bytes.

For every published PDF card, ``<data_root>/ocr/<card_id>/meta.json``
``pdf_sha256`` must equal the latest ``.pdf`` row ``byte_sha256`` in the
asset-bytes registry, or a ``resave-content-verified`` row in
``data/byte-change-dispositions.jsonl`` must cover exactly that pair.

A mismatch exits 1 and lists the card, both shas and the disposition status.
A card with no ``meta.json`` also exits 1; it is listed and counted separately
(``missing OCR``) from stale inputs. An unreadable input fails closed. Repo and data root
only; no network.

Usage::

    python scripts/check_ocr_input_freshness.py [--data-root DIR]
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


class FreshnessError(Exception):
    """An input the gate needs is missing or unreadable, so the run cannot pass."""


def _pdf_card_ids(manifest: Path) -> list[str]:
    try:
        cards = json.loads(manifest.read_text(encoding="utf-8")).get("cards")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise FreshnessError(f"cannot read manifest {manifest}: {exc}") from exc
    if not isinstance(cards, list):
        raise FreshnessError(f"manifest {manifest} has no 'cards' list")
    return sorted({c["card_id"] for c in cards if isinstance(c, dict) and c.get("card_id")})


def check(
    manifest: Path,
    registry: Path,
    dispositions: dict[tuple[str, str], Disposition],
    data_root: Path,
) -> tuple[list[str], list[str], list[str], int]:
    """``(stale, covered, missing, checked)``: report lines for the first three."""
    if not (data_root / "ocr").is_dir():
        raise FreshnessError(
            "PURSUE_DATA_ROOT must point at the data root containing ocr/ "
            f"(looked in {data_root}, which has no ocr/ directory)"
        )
    try:
        registry_sha = load_registry_sha_map(registry)
    except (OSError, ValueError) as exc:
        raise FreshnessError(f"cannot read registry {registry}: {exc}") from exc
    stale: list[str] = []
    covered: list[str] = []
    missing: list[str] = []
    checked = 0
    # Published PDF cards: in the manifest, with a PDF row in the registry.
    for card_id in _pdf_card_ids(manifest):
        new = registry_sha.get(card_id)
        if new is None:
            continue
        checked += 1
        meta = data_root / "ocr" / card_id / "meta.json"
        if not meta.is_file():
            missing.append(card_id)
            continue
        try:
            old = json.loads(meta.read_text(encoding="utf-8")).get("pdf_sha256")
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise FreshnessError(f"cannot read {meta}: {exc}") from exc
        if old == new:
            continue
        if old and covers(dispositions, card_id, old, new):
            covered.append(f"{card_id} ocr={old} registry={new} (covered by disposition)")
        else:
            stale.append(f"{card_id} ocr={old} registry={new} (no disposition covers this pair)")
    return stale, covered, missing, checked


def main(argv: list[str] | None = None) -> int:
    data = REPO_ROOT / "data"
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, default=data / "manifests" / "latest.json")
    parser.add_argument("--registry", type=Path, default=data / "asset-bytes-registry.jsonl")
    parser.add_argument(
        "--dispositions", type=Path, default=data / "byte-change-dispositions.jsonl"
    )
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        data_root = args.data_root or Settings().data_root
        dispositions = load_byte_change_dispositions(args.dispositions)
        stale, covered, missing, checked = check(
            args.manifest, args.registry, dispositions, data_root
        )
    except (FreshnessError, ByteDispositionError) as exc:
        print(f"ocr input freshness: ERROR: {exc}", file=sys.stderr)
        return 1
    lines = [f"stale OCR input: {s}" for s in stale]
    lines += [f"covered: {c}" for c in covered]
    lines += [f"missing OCR meta.json: {c}" for c in missing]
    counts = (
        f"{checked} PDF cards checked, {len(stale)} stale, {len(covered)} covered, "
        f"missing OCR: {len(missing)}"
    )
    failed = bool(stale or missing)
    lines.append(f"ocr input freshness: {'FAILED' if failed else 'OK'} ({counts})")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
