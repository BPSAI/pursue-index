/**
 * Pure helpers for the `Cleaned` reader-mode overlay.
 *
 * Loads + filters the lazily-fetched `web/public/data/pages-cleaned.json` to the
 * pages relevant to the active card. Idempotent + side-effect-free so it
 * can be unit-tested without `fetch`.
 *
 * The shape mirrors the build script `scripts/build_pages_cleaned.py`:
 *
 *   { meta: { ..., model_id, cards_covered }, pages: [ ... ] }
 *
 * Each page row carries the full provenance tuple (model, prompt sha,
 * input sha, output sha, generated_at) so the chat retriever can
 * disambiguate cleaned vs raw at citation time without parsing markers
 * embedded in the rendered text.
 */

export interface CleanedPage {
  id: string;
  card_id: string;
  page: number;
  title: string;
  text: string;
  model_id: string;
  prompt_sha256: string;
  input_sha256: string;
  output_sha256: string;
  generated_at: string;
  /**
   * When set, the cleanup pass did not produce
   * usable cleaned text for this page. Row is still emitted so
   * (card_id, page) coverage in `pages-cleaned.json` keeps the same
   * page sequence as `pages.json` — the UI paginates by array index
   * (`pages[activePage-1]`) and would otherwise mis-route deep links.
   *
   *   - `"empty_input"`       — source OCR was blank; render as a normal
   *                             empty page (mirrors Raw-mode `[BLANK]`).
   *   - `"length_divergence"` — model reply differed too much from the
   *                             input; raw fallback stripped so it
   *                             doesn't ship under the "cleaned" label.
   *                             Render a notice + Raw-mode link.
   *   - `"content_filter"`    — Anthropic's moderation declined to
   *                             return cleaned output for this page.
   *                             Render the "[CLEANUP UNAVAILABLE —
   *                             content filter]" notice + Raw-mode
   *                             link; mirrors `length_divergence` in
   *                             behavior but distinguishable in copy.
   *
   * Kept as the wider `CleanupSkipReason | string` so an unknown future
   * reason from the Python side (added in `build_pages_cleaned.py`
   * before this file is updated) doesn't break the runtime type read —
   * the UI gates render decisions through `requiresUiNotice` and falls
   * back to the generic `[BLANK]` path otherwise.
   */
  cleanup_skipped?: CleanupSkipReason | string;
}

/**
 * Canonical list of `cleanup_skipped` reasons. Mirrors the Python-side
 * `CLEANUP_SKIP_REASONS` in `scripts/build_pages_cleaned.py` —
 * single-source-of-truth on each side of the JSON boundary so a future
 * fourth reason is a one-line add on each side.
 */
export const CLEANUP_SKIP_REASONS = [
  "empty_input",
  "length_divergence",
  "content_filter",
] as const;

export type CleanupSkipReason = (typeof CLEANUP_SKIP_REASONS)[number];

/**
 * Returns true when the skip reason should render the "[CLEANUP
 * UNAVAILABLE]" notice (vs falling through to the generic `[BLANK]`
 * path). `empty_input` intentionally returns false — empty raw OCR is
 * indistinguishable from a blank page and renders consistently with
 * Raw mode's `[BLANK]` rather than under a cleanup-specific notice.
 */
export function requiresUiNotice(
  reason: CleanupSkipReason | string | undefined,
): boolean {
  return reason === "length_divergence" || reason === "content_filter";
}

export interface CleanedMeta {
  generated_at: string;
  source: string;
  cards_covered: string[];
  page_count: number;
  model_id: string;
  prompt_sha256: string;
}

export interface CleanedPayload {
  meta: CleanedMeta;
  pages: CleanedPage[];
}

/**
 * Pick the cleaned-page rows for a given card, sorted by page number.
 * Returns `[]` when the payload is null (fetch in flight, 404, or the
 * pilot didn't cover this card).
 */
export function filterCleanedPages(
  payload: CleanedPayload | null,
  cardId: string,
): CleanedPage[] {
  if (!payload) return [];
  const out = payload.pages.filter((p) => p.card_id === cardId);
  out.sort((a, b) => a.page - b.page);
  return out;
}
