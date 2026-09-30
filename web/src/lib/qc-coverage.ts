/**
 * The QC denominators for /methodology, from `public/data/qc-coverage.json`.
 *
 * The clean-QC bundle only lists the cards the page-level judge covered, so
 * its figures say nothing about the rest of the corpus. qc-coverage.json
 * (built by scripts/build_qc_coverage.py, gated in CI) gives every distinct
 * manifest card one status; this turns it into plain sentences. Every number
 * comes from the payload, and a clause whose count is zero is left out.
 *
 * Two phrasings are conditional on the payload rather than assumed:
 *   - "all PDF documents with OCR text" only when every PDF card is judged
 *     and every judged card is a PDF;
 *   - "videos" only when every no-text card is a video-only card.
 */

export interface QcCoverageCard {
  card_id: string;
  asset_types: string[];
  status: string;
  vision_text_pages?: number[];
}

export interface QcCoverage {
  total_cards: number;
  status_counts: Record<string, number>;
  unverified_other: string[];
  vision_text_pages_in_judged_cards: { cards: number; pages: number };
  cards: QcCoverageCard[];
}

const fmt = (n: number) => n.toLocaleString("en-US");

function count(n: number, singular: string, plural: string): string {
  return `${fmt(n)} ${n === 1 ? singular : plural}`;
}

const verb = (n: number, singular: string, plural: string) => (n === 1 ? singular : plural);

function joinAnd(parts: string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

export function describeQcCoverage(doc: QcCoverage): string[] {
  const n = (status: string) => doc.status_counts[status] ?? 0;
  const judged = n("judged");
  const lines: string[] = [];

  const pdfCards = doc.cards.filter((c) => c.asset_types.includes("PDF"));
  const judgedCards = doc.cards.filter((c) => c.status === "judged");
  const allPdfJudged =
    judged > 0 &&
    pdfCards.every((c) => c.status === "judged") &&
    judgedCards.every((c) => c.asset_types.includes("PDF"));
  lines.push(
    `Of ${count(doc.total_cards, "card", "cards")}, ${fmt(judged)}` +
      (allPdfJudged ? " (all PDF documents with OCR text)" : "") +
      ` ${verb(judged, "is", "are")} QC-judged page by page.`,
  );

  const vision = n("unverified_vision");
  const transcripts = n("unverified_transcript");
  const unverified: string[] = [];
  if (vision > 0) unverified.push(count(vision, "image description", "image descriptions"));
  if (transcripts > 0) unverified.push(count(transcripts, "audio transcript", "audio transcripts"));
  if (unverified.length > 0) {
    const plural = vision + transcripts > 1;
    lines.push(`${joinAnd(unverified)} ${plural ? "are" : "is"} not yet independently verified.`);
  }

  const noText = n("no_text");
  if (noText > 0) {
    const allVideo = doc.cards
      .filter((c) => c.status === "no_text")
      .every((c) => c.asset_types.length === 1 && c.asset_types[0] === "VID");
    const subject = allVideo ? count(noText, "video", "videos") : count(noText, "card", "cards");
    lines.push(`${subject} ${verb(noText, "carries", "carry")} no text.`);
  }

  const other = doc.unverified_other;
  if (other.length > 0) {
    lines.push(
      `${count(other.length, "other card", "other cards")} ${verb(other.length, "is", "are")} ` +
        `not yet verified: ${other.join(", ")}.`,
    );
  }

  const vp = doc.vision_text_pages_in_judged_cards;
  if (vp.pages > 0) {
    lines.push(
      `Within the judged documents, ${count(vp.pages, "image-only page", "image-only pages")} ` +
        `across ${count(vp.cards, "card", "cards")} ${verb(vp.pages, "carries", "carry")} our vision ` +
        `description instead of OCR; ${vp.pages === 1 ? "that description is" : "those descriptions are"} ` +
        `not yet independently verified.`,
    );
  }

  return lines;
}
