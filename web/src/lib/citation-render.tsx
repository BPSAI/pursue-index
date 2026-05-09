// Render assistant text with inline [card_id:page] citations as
// linked chips. The model emits citations like "[a1b2c3d4e5f6:5]" — we
// match the bracket form, look up the matching passage from the
// citations list, and replace it with an <a> chip that opens the card
// page in a new tab. Tokens that look like citations but don't match a
// known passage are rendered as plain text.

import type { Citation } from "./llm-provider";

const CITE_RE = /\[([0-9a-f]{6,})(?::(\d+))?\]/g;

interface CiteSegment {
  kind: "text" | "cite";
  value: string;
  citation?: Citation;
  index?: number; // 1-based numeric label for display
}

export function segmentWithCitations(
  text: string,
  citations: Citation[],
  base: string,
): unknown[] {
  // Build a map keyed by `${card_id}:${page}` for exact matches and
  // a fallback by card_id (in case the model omits the page).
  const byKey = new Map<string, { c: Citation; idx: number }>();
  citations.forEach((c, i) => {
    byKey.set(`${c.card_id}:${c.page}`, { c, idx: i + 1 });
    // first occurrence by card_id wins
    if (!byKey.has(c.card_id)) byKey.set(c.card_id, { c, idx: i + 1 });
  });
  const out: CiteSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE_RE)) {
    const start = m.index ?? 0;
    if (start > last) {
      out.push({ kind: "text", value: text.slice(last, start) });
    }
    const cardId = m[1];
    const page = m[2];
    const key = page ? `${cardId}:${page}` : cardId;
    const hit = byKey.get(key) || byKey.get(cardId);
    if (hit) {
      out.push({ kind: "cite", value: m[0], citation: hit.c, index: hit.idx });
    } else {
      // Unknown citation — render literal so the user can see it but
      // not click through to a bogus URL.
      out.push({ kind: "text", value: m[0] });
    }
    last = start + m[0].length;
  }
  if (last < text.length) {
    out.push({ kind: "text", value: text.slice(last) });
  }
  return out.map((seg, i) => {
    if (seg.kind === "text") {
      return seg.value;
    }
    const c = seg.citation!;
    const href = `${base}/card/${c.card_id}?q=${encodeURIComponent("citation")}#page-${c.page}`;
    return (
      <a
        key={i}
        href={href}
        target="_blank"
        rel="noreferrer"
        title={c.title}
        class="inline-flex items-baseline px-1 mx-0.5 text-[10px] font-mono text-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-signal-green)] border border-[color:var(--color-border)] hover:border-[color:var(--color-signal-cyan)] transition-colors"
      >
        [{seg.index}]
      </a>
    );
  });
}
