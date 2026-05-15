"""Pre-classify omnibus-pattern cards in the proposals queue as abstentions.

Why this exists: during the 2026-05-15 review pass the operator discovered
that decade-spanning omnibus files (FBI 62-HQ-83894 sections, DOW Box 7
incident summaries, 1940s Generals files, etc.) have many defensible
dates throughout — incident dates, response-correspondence dates,
routing dates, declassification stamps, sub-document dates. The
writer agent picked one (usually a declassification stamp or the most
recent date in OCR), but no single date is correct for these files.

Forcing a date is worse than abstaining. This script walks the proposals
queue, identifies cards by filename/title pattern, and rewrites their
proposals as abstentions with templated coverage-range reasons. The
operator's review of these cards then becomes a quick A (accept) or
E (edit-the-reason) — saving review time without losing editorial
control.

Read once; write once. Doesn't touch the operator-approved
``display_dates.json`` — that file is the source of truth and only
the curate UI writes to it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROPOSALS = _REPO_ROOT / "data" / "display_dates_proposals.jsonl"
DEFAULT_MANIFEST = _REPO_ROOT / "data" / "manifests" / "latest.json"


# (regex, template_reason). Order matters — first match wins.
#
# `62-HQ-83894` matches both the omnibus section files AND the individual
# serial documents within them. We only want the SECTION files (decade-
# spanning compilations); individual serials are single documents with
# defensible dates. Two patterns: include 'Section', exclude 'Serial'
# and 'SUB_'.
_PATTERNS: list[tuple[str, str]] = [
    (
        r"62-?HQ-?83894.*section",
        "FBI 62-HQ-83894 is the Bureau's general flying-disc case file (1947-1968). "
        "Each section is a decade-spanning compilation of correspondence, routing slips, "
        "declassification stamps, and sub-document dates with no single defensible document "
        "date. Surface the file's coverage range in /timeline instead.",
    ),
    (
        r"box[_ ]?7|box7",
        "DOW Box 7 incident summaries collection — a multi-incident container covering "
        "Project Blue Book incidents spanning multiple years. No single document date applies "
        "to the file as a whole; individual incident sub-sheets carry their own dates.",
    ),
    (
        r"general[_ ]+19\d\d",
        "1940s FBI Generals file — a multi-year correspondence compilation. "
        "Contains documents with incident dates, response-letter dates, routing dates, and "
        "declassification stamps spanning the file's coverage period. No single document "
        "date applies.",
    ),
    (
        r"numeric[_ ]+file",
        "FBI numeric-file is a multi-year correspondence compilation. Documents within "
        "span multiple incidents and reply chains; no single date applies to the file.",
    ),
    (
        r"records[_ ]+relating[_ ]+to|collection[_ ]+and[_ ]+dissemination",
        "Multi-year records compilation. Spans multiple incidents, response chains, and "
        "declassification batches. No single defensible document date.",
    ),
    (
        r"_vol[_ ]?\d|\bvol[_ ]\d",
        "Multi-volume file. By construction, contains documents from across the volume's "
        "coverage period with no single defensible file-level date.",
    ),
    (
        r"flying[_ ]+disc.*194\d|319\.1.*flying[_ ]+disc",
        "Flying Discs compilation file (Air Force 319.1 series) — a multi-document "
        "compilation spanning the early flying-disc reporting era. Individual sub-documents "
        "carry their own dates.",
    ),
    (
        r"incident[_ ]?summar",
        "Multi-incident summary collection. Compiles per-incident sheets each with their "
        "own date; no single file-level date applies.",
    ),
    (
        # Generic "_section_N" match — but NOT a serial/SUB which is single-document
        r"(?<!serial)(?<![Ss]ub)_section_\d|_section\d",
        "Multi-section file. Sections compile documents across years with no single "
        "defensible file-level date.",
    ),
]


def _match_pattern(filename: str, title: str) -> str | None:
    text = f"{filename} {title}".lower()
    for pat, reason in _PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return reason
    return None


def _load_proposals(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _save_proposals(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text())
    cards_by_id = {c["card_id"]: c for c in manifest.get("cards", [])}

    proposals = _load_proposals(args.proposals)
    if not proposals:
        print(f"No proposals at {args.proposals}", file=sys.stderr)
        return 1

    rewritten = 0
    untouched = 0
    already_abstain = 0
    changes: list[tuple[str, str, str]] = []

    out_rows: list[dict[str, Any]] = []
    for p in proposals:
        cid = p["card_id"]
        card = cards_by_id.get(cid, {})
        filename = card.get("asset_filename") or ""
        title = card.get("title") or ""
        reason = _match_pattern(filename, title)
        if reason is None:
            out_rows.append(p)
            untouched += 1
            continue

        # Already abstaining? Leave the agent's reason in place — it's
        # probably equivalent and we trust the agent's first-hand assessment.
        if p.get("display_date") is None and p.get("display_date_abstention"):
            already_abstain += 1
            out_rows.append(p)
            continue

        # Rewrite as abstention with templated reason. Preserve the agent's
        # original proposal in _proposal_metadata for audit.
        original = {
            "display_date": p.get("display_date"),
            "display_date_range": p.get("display_date_range"),
            "display_date_evidence": p.get("display_date_evidence"),
            "display_date_evidence_card_ref": p.get("display_date_evidence_card_ref"),
        }
        new_p = {
            "card_id": cid,
            "display_date": None,
            "display_date_range": None,
            "display_date_evidence": p.get("display_date_evidence"),
            "display_date_evidence_card_ref": p.get("display_date_evidence_card_ref"),
            "display_date_abstention": reason,
            "display_date_curator": p.get("display_date_curator"),
            "display_date_approved_at": None,
            "_proposal_metadata": {
                **(p.get("_proposal_metadata") or {}),
                "reclassified_as_omnibus": True,
                "agent_original_proposal": original,
            },
        }
        out_rows.append(new_p)
        rewritten += 1
        changes.append((cid, p.get("display_date") or "(none)", title[:50]))

    print(f"Proposals: {len(proposals)} total")
    print(f"  rewritten as omnibus abstentions: {rewritten}")
    print(f"  already abstaining (left alone):  {already_abstain}")
    print(f"  untouched (single-document):       {untouched}")
    print()
    if changes:
        print("Rewritten cards:")
        for cid, original_date, title in changes:
            print(f"  {cid}  was: {original_date:12s}  {title}")

    if args.dry_run:
        print("\n(dry-run; no file written)")
        return 0

    _save_proposals(args.proposals, out_rows)
    print(f"\nWrote {len(out_rows)} rows to {args.proposals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
