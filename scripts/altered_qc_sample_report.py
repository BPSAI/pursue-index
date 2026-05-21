"""Generate a markdown QC report sampling cards from each
classification bucket, with side-by-side links so a human can
eyeball-verify the displayed diff matches the rendered PDFs.

The Python invariant tests cover *internal* data consistency
(buckets sum, no presentation_only leaks into diffs, etc.). This
script covers *external* truthfulness — does the green
"presentation_only" banner actually correspond to PDFs that look
identical? Does the amber "visually_changed" banner match a card
where the eye sees a real difference?

Usage::

    python scripts/altered_qc_sample_report.py --n 5

Defaults to 5 random cards per bucket. Writes
``data/altered-qc-report.md``; not committed (gitignored under
``data/altered-qc-report.md`` would be cleaner, but for now the
operator just inspects locally).

Random seed: stable per-day so repeated runs in the same day are
reproducible.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CLASSIFICATION = _REPO_ROOT / "data" / "altered-classification.json"
DEFAULT_BYTE_HISTORY = _REPO_ROOT / "web" / "src" / "data" / "byte-history.json"
DEFAULT_DIFFS = _REPO_ROOT / "web" / "src" / "data" / "altered-diffs.json"
DEFAULT_OUT = _REPO_ROOT / "data" / "altered-qc-report.md"

# Effective bucket order for the report. Visually_identical / changed
# are sub-classes of no_text_layer; flatten for sampling.
_BUCKETS = (
    "content_changed_text",        # class: content_changed (text-layer)
    "content_changed_visual",      # class: no_text_layer + visual_class: visually_changed
    "presentation_only_text",      # class: presentation_only
    "presentation_only_visual",    # class: no_text_layer + visual_class: visually_identical
    "asset_type_change",
    "unknown",
)


def _effective_bucket(entry: dict) -> str:
    cls = entry.get("class")
    if cls == "no_text_layer":
        vc = entry.get("visual_class")
        if vc == "visually_identical":
            return "presentation_only_visual"
        if vc == "visually_changed":
            return "content_changed_visual"
        return "unknown"  # still pending
    if cls == "presentation_only":
        return "presentation_only_text"
    if cls == "content_changed":
        return "content_changed_text"
    if cls == "asset_type_change":
        return "asset_type_change"
    return "unknown"


def _bucket_cards(classification: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {b: [] for b in _BUCKETS}
    for cid, entry in classification["cards"].items():
        out[_effective_bucket(entry)].append(cid)
    for cards in out.values():
        cards.sort()
    return out


def _sample(card_ids: list[str], n: int, seed: int) -> list[str]:
    if len(card_ids) <= n:
        return list(card_ids)
    rng = random.Random(seed)
    return sorted(rng.sample(card_ids, n))


def _format_card_row(
    cid: str, entry: dict, byte_history: dict, diffs: dict, base_url: str
) -> str:
    bh = byte_history.get(cid, [])
    current = bh[0] if bh else {}
    oldest = bh[-1] if bh else {}
    summary = diffs.get(cid, {}).get("summary", {})

    pre_link = f"`/{oldest.get('archive_key', '')}`" if oldest else "_n/a_"
    post_link = f"`/{current.get('archive_key', '')}`" if current else "_n/a_"
    page_url = f"{base_url}/altered/{cid}/"

    summary_str = ""
    if summary:
        summary_str = (
            f"rmv={summary.get('removed_words', 0)} / "
            f"add={summary.get('added_words', 0)} / "
            f"mod={summary.get('modified_sentences', 0)}"
        )

    notes = []
    if entry.get("max_page_bit_diff") is not None:
        notes.append(
            f"max bit-diff: {entry['max_page_bit_diff']}/"
            f"{entry.get('hash_size_bits', '?')}"
        )
    if entry.get("pre_pages") is not None:
        notes.append(f"pages: {entry['pre_pages']}→{entry.get('post_pages', '?')}")
    notes_str = " · ".join(notes) if notes else ""

    return (
        f"- **`{cid}`** — [/altered/{cid}/]({page_url})\n"
        f"  - Pre-edit: {pre_link}\n"
        f"  - Current:  {post_link}\n"
        + (f"  - Diff summary: {summary_str}\n" if summary_str else "")
        + (f"  - Classification details: {notes_str}\n" if notes_str else "")
    )


def _render_bucket(
    name: str, sampled: list[str], all_in_bucket: list[str],
    classification: dict, byte_history: dict, diffs: dict, base_url: str,
) -> str:
    out = [f"\n## {name} ({len(all_in_bucket)} total, sampled {len(sampled)})\n"]
    out.append(_bucket_description(name))
    out.append("\n**Reviewer task**: open each sampled card's page side-by-side\n"
               "with the pre-edit and current PDF archive URLs. Confirm the\n"
               "banner / diff matches what your eye sees.\n\n")
    for cid in sampled:
        entry = classification["cards"].get(cid, {})
        out.append(_format_card_row(cid, entry, byte_history, diffs, base_url))
    return "".join(out)


_BUCKET_DESCRIPTIONS = {
    "content_changed_text": (
        "Text layer differs across pre/post. Real upstream edit "
        "detected via authoritative PDF text comparison. The OCR diff "
        "should show meaningful content delta — verify the highlighted "
        "removed/added/modified segments correspond to actual edits "
        "(redaction additions, paragraph rewrites, classification "
        "marker changes)."
    ),
    "content_changed_visual": (
        "No extractable text layer (image-only scan), but perceptual "
        "hashing detected real visual changes between rendered pages. "
        "OCR diff is the best textual signal but has some Sonnet "
        "non-determinism noise. Verify the diff captures the same "
        "regions that look visually different on the rendered pages."
    ),
    "presentation_only_text": (
        "Text layer is byte-identical across pre/post after whitespace "
        "normalization. Bytes changed but content didn't — re-encoding, "
        "metadata, font subset. **The page should show no diff content** "
        "(green banner only). Open both PDFs and confirm the text reads "
        "identically; if it doesn't, the text-layer extraction is "
        "missing something."
    ),
    "presentation_only_visual": (
        "Image-only scan; perceptual-hash comparison shows all pages "
        "are visually identical within ~0.8% bit difference. **Page "
        "should show no diff content** (green banner only). Open both "
        "PDFs side-by-side and confirm visual identity to the eye."
    ),
    "asset_type_change": (
        "Upstream replaced the asset type (typically video → PDF report). "
        "Pre-edit content doesn't exist as text. Page should show "
        "'TEXT DIFF NOT AVAILABLE' with both archive links."
    ),
    "unknown": (
        "Cards with no_text_layer class and no visual_class — visual "
        "classification hasn't run. Run "
        "`scripts/classify_no_text_layer_visually.py` to resolve."
    ),
}


def _bucket_description(name: str) -> str:
    return f"_{_BUCKET_DESCRIPTIONS.get(name, name)}_\n"


def _render_report(
    *, classification: dict, byte_history: dict, diffs: dict,
    n_per_bucket: int, base_url: str, seed: int,
) -> str:
    buckets = _bucket_cards(classification)
    out = [
        "# /altered/ QC sample report\n\n",
        f"Generated: {dt.datetime.utcnow().isoformat()}Z · seed={seed}\n\n",
        "Random-sample of cards from each classification bucket for "
        "human eyeball verification. The Python invariants in "
        "`tests/integration/test_altered_classification_consistency.py` "
        "cover internal data consistency; this report covers external "
        "truthfulness — does the classification match what a human "
        "sees when comparing the pre-edit and current PDFs side-by-side?\n",
    ]
    for bucket in _BUCKETS:
        cards = buckets[bucket]
        sampled = _sample(cards, n_per_bucket, seed=seed + hash(bucket) % 1000)
        out.append(_render_bucket(
            bucket, sampled, cards, classification, byte_history, diffs, base_url
        ))
    return "".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION)
    parser.add_argument("--byte-history", type=Path, default=DEFAULT_BYTE_HISTORY)
    parser.add_argument("--diffs", type=Path, default=DEFAULT_DIFFS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--n", type=int, default=5,
                        help="Sample size per bucket. Default 5.")
    parser.add_argument("--base-url", default="https://pursueindex.com")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Sampling seed. Defaults to today's UTC date as an int "
        "(stable per day; changes daily for fresh samples).",
    )
    args = parser.parse_args(argv)

    if args.seed is None:
        today = dt.datetime.utcnow().date()
        args.seed = today.toordinal()

    classification = json.loads(args.classification.read_text(encoding="utf-8"))
    byte_history = json.loads(args.byte_history.read_text(encoding="utf-8"))
    diffs_blob = json.loads(args.diffs.read_text(encoding="utf-8"))
    diffs = diffs_blob.get("diffs", {})

    report = _render_report(
        classification=classification, byte_history=byte_history,
        diffs=diffs, n_per_bucket=args.n, base_url=args.base_url,
        seed=args.seed,
    )
    args.out.write_text(report, encoding="utf-8")
    print(f"altered_qc_sample_report: {args.out} (seed={args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
