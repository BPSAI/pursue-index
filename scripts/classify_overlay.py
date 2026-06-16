#!/usr/bin/env python3
"""Classify newly-appended asset-bytes-registry rows: true overlay vs net-new.

The daily byte-verify workflow appends a registry row whenever it archives an
asset. Previously it opened a `silent-overlay-detected` integrity issue on ANY
appended row — so it false-fired after every release promote (net-new cards
getting archived for the first time), eroding signal on a real-threat channel.

The actual threat is a *same-URL-different-bytes overlay*: an `asset_url` that
already existed in the registry reappears with a DIFFERENT `byte_sha256`
(upstream silently swapping bytes under a stable URL). A brand-new `asset_url`
is just normal archival, not a threat.

This module classifies the rows added between a prior and current registry and
reports only the true overlays. Pure functions + a thin CLI; no I/O beyond the
CLI reading two JSONL paths. Mirrors the `classify_tranche` testable-pure shape.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OverlayClassification:
    """Result of classifying appended registry rows."""

    overlays: list[dict] = field(default_factory=list)   # existing asset_url, NEW byte_sha256
    net_new: list[dict] = field(default_factory=list)    # asset_url not seen before

    @property
    def is_overlay(self) -> bool:
        return bool(self.overlays)


def _row_identity(row: dict) -> tuple[str, str]:
    return (row.get("asset_url", ""), row.get("byte_sha256", ""))


def classify_overlay_rows(
    prior_rows: list[dict], current_rows: list[dict]
) -> OverlayClassification:
    """Classify rows present in ``current_rows`` but not ``prior_rows``.

    A newly-present (asset_url, byte_sha256) pair is an OVERLAY iff its
    ``asset_url`` already appeared in ``prior_rows`` under a different
    ``byte_sha256``. A new ``asset_url`` is net-new (benign archival).
    Rows already present in prior (same url+sha) are ignored (unchanged).
    """
    prior_identities = {_row_identity(r) for r in prior_rows}
    prior_url_shas: dict[str, set[str]] = {}
    for r in prior_rows:
        url = r.get("asset_url", "")
        if url:
            prior_url_shas.setdefault(url, set()).add(r.get("byte_sha256", ""))

    overlays: list[dict] = []
    net_new: list[dict] = []
    for r in current_rows:
        if _row_identity(r) in prior_identities:
            continue  # unchanged row
        url = r.get("asset_url", "")
        if url and url in prior_url_shas:
            overlays.append(r)  # existing URL, new sha → the real threat
        else:
            net_new.append(r)
    return OverlayClassification(overlays=overlays, net_new=net_new)


def _read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        return []
    return rows


def main(argv: list[str]) -> int:
    """CLI: classify_overlay.py <prior.jsonl> <current.jsonl>.

    Prints a stable kv line the workflow parses:
      ``overlay-classify overlays=<N> net_new=<M>``
    followed by one ``overlay\\t<card_id>\\t<asset_url>\\t<byte_sha256>`` line
    per true overlay (for the issue body). Exit 0 always (classification, not
    a gate); the caller keys on ``overlays=``.
    """
    if len(argv) != 3:
        print("usage: classify_overlay.py <prior.jsonl> <current.jsonl>", file=sys.stderr)
        return 2
    prior = _read_jsonl(argv[1])
    current = _read_jsonl(argv[2])
    result = classify_overlay_rows(prior, current)
    print(f"overlay-classify overlays={len(result.overlays)} net_new={len(result.net_new)}")
    for r in result.overlays:
        print(f"overlay\t{r.get('card_id','')}\t{r.get('asset_url','')}\t{r.get('byte_sha256','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
