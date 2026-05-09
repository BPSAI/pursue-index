/**
 * Highlight helpers shared between SearchIsland (result snippets) and
 * CardOcrIsland (in-page OCR highlighting when ?q= is present).
 *
 * The strategy is the same in both places:
 *   1. Tokenize the query into search terms (alphanumeric runs).
 *   2. Build one regex that matches any term, with word-boundary leniency.
 *   3. Walk the source text and emit alternating "text" / "match" segments.
 *
 * The caller renders the segments — we don't return HTML, so the call sites
 * stay XSS-safe even though the OCR text itself is trusted.
 */

export type Segment =
  | { kind: "text"; value: string }
  | { kind: "match"; value: string };

const NON_WORD = /[^\p{L}\p{N}]+/u;

/** Normalize a query into alphanumeric tokens; empty array for empty query. */
export function tokenize(query: string): string[] {
  return query
    .trim()
    .split(NON_WORD)
    .filter((t) => t.length > 1);
}

/** Escape a string for use in a RegExp character class / literal. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Build a global, case-insensitive regex that matches any of `terms` as
 * a whole word. Returns null for empty input. Lenient on punctuation:
 * a run like `aliens.` matches `aliens` cleanly because the regex matches
 * the term and surrounding non-word chars sit outside the capture.
 */
export function buildHighlightRegex(terms: string[]): RegExp | null {
  const safe = terms.filter((t) => t.length > 0).map(escapeRegExp);
  if (safe.length === 0) return null;
  // Sort longer first so "alienate" doesn't get matched as "alien" first.
  safe.sort((a, b) => b.length - a.length);
  // \b uses ASCII word chars in JS; with Unicode flag, lookarounds give
  // us better behavior for non-ASCII text.
  return new RegExp(`(?<![\\p{L}\\p{N}])(?:${safe.join("|")})(?![\\p{L}\\p{N}])`, "giu");
}

/**
 * Split `text` into alternating text / match segments using `regex`.
 * If `regex` is null, returns a single text segment.
 */
export function splitWithRegex(text: string, regex: RegExp | null): Segment[] {
  if (!regex || !text) return [{ kind: "text", value: text }];
  const out: Segment[] = [];
  let last = 0;
  // Reset state in case the same regex is reused.
  regex.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      out.push({ kind: "text", value: text.slice(last, m.index) });
    }
    out.push({ kind: "match", value: m[0] });
    last = m.index + m[0].length;
    // Guard against zero-width regex pathology.
    if (m[0].length === 0) regex.lastIndex++;
  }
  if (last < text.length) {
    out.push({ kind: "text", value: text.slice(last) });
  }
  return out;
}

/**
 * Find the first character index of any term match in `text`, or -1.
 * Used to center a snippet on the first hit.
 */
export function firstMatchIndex(text: string, regex: RegExp | null): number {
  if (!regex || !text) return -1;
  regex.lastIndex = 0;
  const m = regex.exec(text);
  return m ? m.index : -1;
}

/**
 * Build a snippet of approximately `targetChars` centered on the first
 * match in `text`. Adds an ellipsis at start/end when truncated. If no
 * match found, returns the head of the text.
 */
export function buildSnippet(
  text: string,
  regex: RegExp | null,
  targetChars = 120,
): string {
  if (!text) return "";
  const idx = firstMatchIndex(text, regex);
  const half = Math.floor(targetChars / 2);
  if (idx < 0) {
    return text.length > targetChars ? text.slice(0, targetChars).trimEnd() + "…" : text;
  }
  const start = Math.max(0, idx - half);
  const end = Math.min(text.length, idx + half);
  // Try not to chop in the middle of a word at the edges.
  let from = start;
  while (from > 0 && /\S/.test(text[from - 1] ?? "") && idx - from < targetChars) {
    from--;
  }
  let to = end;
  while (to < text.length && /\S/.test(text[to] ?? "") && to - idx < targetChars) {
    to++;
  }
  let snip = text.slice(from, to).replace(/\s+/g, " ").trim();
  if (from > 0) snip = "…" + snip;
  if (to < text.length) snip = snip + "…";
  return snip;
}
