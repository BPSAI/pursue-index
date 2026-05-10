/**
 * Pure helpers for the `Cleaned` reader-mode overlay.
 *
 * Loads + filters the lazily-fetched `web/public/data/pages-cleaned.json`
 * (Option C in `.paircoder/plans/llm-cleaned-reading-text.md`) to the
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
