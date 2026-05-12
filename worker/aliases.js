// Card-alias resolver.
//
// When upstream re-catalogs a document, the new (asset_url, title) tuple
// produces a new card_id. The scripts/tranche_diff.py pass writes the
// old → new mapping into `data/card-aliases.json` (also deployed at
// /data/card-aliases.json via the static-assets binding).
//
// This module:
//   1. Loads card-aliases.json from the ASSETS binding, builds a fast
//      lookup index. Append-only semantics: later entries supersede
//      earlier ones for the same old_card_id; `operator_revoke` rows
//      remove the alias.
//   2. Provides `tryHandleCardAlias(request, idx)` to 301 a
//      `/card/<old_id>` request to `/card/<new_id>`.
//   3. Provides `resolveAlias(idx, cardId)` so the index.js dispatcher
//      can stamp `X-Pursue-Aliased-To` on `/pdf/<old_id>.pdf`
//      responses (the PDF route itself continues to serve the
//      preserved bytes from R2 at the old key — preservation contract).
//
// Failure mode: if card-aliases.json is missing, malformed, or any
// row is shaped wrong, we silently fall through with an empty index.
// Alias resolution is optional infrastructure — a bad aliases file
// must NEVER take down the worker for cards that have nothing to do
// with aliasing.

import { CARD_ID_RE } from "./pdf.js";

const CARD_PATH_RE = /^\/card\/([a-f0-9]{16})(\/?)$/;
const PDF_PATH_RE = /^\/pdf\/([a-f0-9]{16})\.pdf$/;
const ALIAS_ASSET_PATH = "/data/card-aliases.json";

/**
 * Build the in-memory alias index from the parsed aliases.json payload.
 *
 * Iteration order: oldest → newest (the file is append-only, so file
 * order IS chronological). For each `old_card_id` we keep the most
 * recently established row; if that row's method is `operator_revoke`
 * we delete the entry entirely. Subsequent re-establish rows (for the
 * same old_card_id) bring the alias back. The end state of this loop
 * is the live alias map.
 *
 * Malformed rows (non-object, missing required fields) are skipped
 * without throwing — see module-level failure-mode comment.
 */
export function buildAliasIndex(payload) {
  const idx = new Map();
  if (!payload || typeof payload !== "object") return idx;
  const rows = Array.isArray(payload.aliases) ? payload.aliases : [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const oldId = row.old_card_id;
    if (typeof oldId !== "string" || !CARD_ID_RE.test(oldId)) continue;
    if (row.method === "operator_revoke") {
      idx.delete(oldId);
      continue;
    }
    const newId = row.new_card_id;
    if (typeof newId !== "string" || !CARD_ID_RE.test(newId)) continue;
    idx.set(oldId, row);
  }
  return idx;
}

/**
 * Load and parse card-aliases.json from the static-assets binding.
 *
 * Returns an empty Map on any error (network, parse, missing file).
 * Never throws — the worker MUST continue to serve non-aliased
 * requests even if the aliases file is corrupt or absent.
 */
export async function loadAliasIndex(env) {
  try {
    const url = new URL(ALIAS_ASSET_PATH, "https://placeholder.invalid");
    const resp = await env.ASSETS.fetch(new Request(url));
    if (!resp || !resp.ok) return new Map();
    const payload = await resp.json();
    return buildAliasIndex(payload);
  } catch {
    return new Map();
  }
}

/**
 * Extract a card_id from `/card/<id>` (with optional trailing slash).
 * Returns the card_id or null if the path doesn't match.
 */
export function parseCardPath(pathname) {
  const m = CARD_PATH_RE.exec(pathname);
  return m ? m[1] : null;
}

/**
 * Extract a card_id from `/pdf/<id>.pdf`.
 * Returns the card_id or null.
 */
export function parsePdfPath(pathname) {
  const m = PDF_PATH_RE.exec(pathname);
  return m ? m[1] : null;
}

/**
 * Look up an alias; return new_card_id or null.
 */
export function resolveAlias(idx, cardId) {
  const row = idx.get(cardId);
  return row ? row.new_card_id : null;
}

/**
 * If the request path is /card/<old_id> and an alias exists, return a
 * 301 Response redirecting to /card/<new_id>. Otherwise null (caller
 * falls through to the normal ASSETS handler, which serves the page
 * for cards in the manifest or 404s).
 *
 * The response body is a small human-readable HTML page explaining
 * the redirect — for the rare case where a browser shows the body
 * (some user agents on slow connections, or curl users hitting the
 * URL directly). The Location header is what 99% of clients follow.
 */
export function tryHandleCardAlias(request, idx) {
  const url = new URL(request.url);
  const m = CARD_PATH_RE.exec(url.pathname);
  if (!m) return null;
  const oldId = m[1];
  const trailing = m[2];
  const row = idx.get(oldId);
  if (!row) return null;
  const newId = row.new_card_id;
  const location = `/card/${newId}${trailing}`;
  const established = row.established || "(date unknown)";
  const body = `<!doctype html><html><head><meta charset="utf-8"><title>Re-cataloged → /card/${newId}</title><meta http-equiv="refresh" content="0; url=${location}"></head><body><p>This card was re-cataloged on ${established} as <a href="${location}"><code>${newId}</code></a> — content unchanged (cryptographically verified).</p><p>aliased from: <code>${oldId}</code></p></body></html>`;
  return new Response(body, {
    status: 301,
    headers: {
      "Location": location,
      "Content-Type": "text/html; charset=utf-8",
      "X-Pursue-Aliased-From": oldId,
      "Cache-Control": "public, max-age=300",
    },
  });
}
