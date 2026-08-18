/**
 * Pure helpers for the homepage search shortcut island.
 *
 * The homepage hero shows a search input but does NOT carry the full
 * MiniSearch index — that lives on `/search`. Submitting from the
 * homepage redirects to `/search?q=<encoded query>` and lets that
 * route pay the hydration cost (pages.json fetch + MiniSearch build)
 * honestly. This moves the 7.1 MB pages.json fetch off the homepage's
 * critical path.
 *
 * Kept in a separate module so the URL-building logic stays
 * unit-testable under `node --test` without spinning up jsdom for
 * the (very small) Preact component.
 */

/**
 * Build the redirect target for a homepage search submit.
 *
 * Trims whitespace and empties → returns `${base}/search` (no query
 * string) so the user lands on the search page with the input ready
 * for fresh keystrokes. Non-empty queries are URI-encoded and
 * appended as `?q=...`. Reserved characters (`?`, `&`, `=`, `#`,
 * `%`, spaces) all encode correctly via `encodeURIComponent`.
 *
 * `base` is normalized: trailing `/` stripped so we never emit a
 * double slash (`//search`), and empty base → `/search` (not
 * `//search` either).
 */
export function buildSearchHref(base: string, query: string): string {
  const normalizedBase = base.replace(/\/$/, "");
  const trimmed = query.trim();
  if (!trimmed) return `${normalizedBase}/search`;
  return `${normalizedBase}/search?q=${encodeURIComponent(trimmed)}`;
}
