"""Raw utterance storage for a transcript sidecar.

A sidecar keeps its utterances once, in ``<card_dir>/utterances.jsonl`` (one
utterance per line), referenced from ``meta.json`` by relative path so a
sidecar can be re-paginated without re-transcribing. Sidecars written before
the file existed carry them inline under ``meta["utterances"]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

UTTERANCES_FILE = "utterances.jsonl"


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_utterances(card_dir: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """A sidecar's stored utterances: the sibling file, else inline in ``meta``.

    Sidecars written before utterances moved to their own file carry them
    inline under ``meta["utterances"]``.
    """
    name = meta.get("utterances_file")
    if name and (card_dir / name).exists():
        return _read_jsonl_rows(card_dir / name)
    return list(meta.get("utterances") or [])


def append_utterances(
    card_dir: Path, prior: dict[str, Any], utterances: list[dict[str, Any]]
) -> None:
    """Append ``utterances`` to the card's utterances file.

    A card whose prior meta still holds utterances inline and has no file yet
    has them moved into the file first, so the raw transcript is stored once.
    """
    path = card_dir / UTTERANCES_FILE
    carried = [] if path.exists() else read_utterances(card_dir, prior)
    with path.open("a", encoding="utf-8") as fh:
        for utterance in [*carried, *utterances]:
            fh.write(json.dumps(utterance) + "\n")
