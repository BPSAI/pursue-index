/**
 * Pure helper layer for the /diff page.
 *
 * The diff island delegates data-shape logic here so the rendering
 * code stays thin and the algorithms are unit-testable without a DOM.
 *
 * Conceptual surface:
 *   parseDiffParams / buildDiffParams — URL state round-trip
 *   selectDefaultPair                  — default snapshot pair for the landing view
 *   resolveAliases                     — card-aliases.json → terminal-id resolver
 *   diffWithAliases                    — rename-aware add/remove/renamed grouping
 *   fieldOnlyChanges                   — cards present in both snapshots with diff'd fields
 *
 * See ``.paircoder/plans/diff-page-arbitrary-pair-selection.md`` for
 * the broader UX context.
 */

import type { AliasEntry, CardMetadata } from "../data/types.ts";

// --- URL state -------------------------------------------------------

export function parseDiffParams(search: string): { from: string | null; to: string | null } {
  // Accept either "?from=...&to=..." or "from=...&to=..." for robustness.
  const qs = search.startsWith("?") ? search.slice(1) : search;
  if (!qs) return { from: null, to: null };
  const params = new URLSearchParams(qs);
  return {
    from: params.get("from"),
    to: params.get("to"),
  };
}

export function buildDiffParams(from: string | null, to: string | null): string {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  return params.toString();
}

// --- Default snapshot pair ------------------------------------------

export function selectDefaultPair(index: string[]): { from: string | null; to: string | null } {
  // Index is chronologically sorted oldest→newest. Default = compare
  // the most recent prior (-2) against the latest (-1). The mental
  // model is "what changed in the latest tranche."
  if (index.length === 0) return { from: null, to: null };
  if (index.length === 1) return { from: null, to: index[0] };
  return { from: index[index.length - 2], to: index[index.length - 1] };
}

// --- Alias resolver -------------------------------------------------

export interface ResolvedAlias {
  terminal: string;
  method: string;
}
export type AliasMap = Record<string, ResolvedAlias>;

export function resolveAliases(rawAliases: AliasEntry[]): AliasMap {
  // Walk operator_revoke tombstones (later entry wins, removes mapping).
  // Then resolve chains so every old_card_id maps to its terminal id.
  const direct: Record<string, { newId: string; method: string }> = {};
  for (const a of rawAliases) {
    if (!a.old_card_id || !a.new_card_id) continue;
    if (a.method === "operator_revoke") {
      delete direct[a.old_card_id];
      continue;
    }
    direct[a.old_card_id] = { newId: a.new_card_id, method: a.method };
  }

  const out: AliasMap = {};
  const MAX_HOPS = 8;
  for (const oldId of Object.keys(direct)) {
    const seen = new Set<string>();
    let cur = oldId;
    let method = direct[oldId].method;
    for (let i = 0; i < MAX_HOPS; i++) {
      if (seen.has(cur)) break; // cycle defense
      seen.add(cur);
      const next = direct[cur];
      if (!next) break;
      cur = next.newId;
    }
    out[oldId] = { terminal: cur, method };
  }
  return out;
}

// --- Diff with alias collapsing ------------------------------------

export interface DiffResult {
  added: CardMetadata[];
  removed: CardMetadata[];
  renamed: Array<{ from: CardMetadata; to: CardMetadata; method: string }>;
}

export function diffWithAliases(
  prev: CardMetadata[],
  curr: CardMetadata[],
  aliases: AliasMap,
): DiffResult {
  const prevById = new Map(prev.map((c) => [c.card_id, c]));
  const currById = new Map(curr.map((c) => [c.card_id, c]));

  const added: CardMetadata[] = [];
  const removed: CardMetadata[] = [];
  const renamed: Array<{ from: CardMetadata; to: CardMetadata; method: string }> = [];

  // Track which prev card_ids were absorbed by a rename so we don't
  // also emit them in `removed`.
  const absorbedFromPrev = new Set<string>();

  // First pass: any prev card_id with an alias whose terminal lands
  // in curr is a confirmed rename. Emit it once and mark both sides.
  for (const prevCard of prev) {
    const a = aliases[prevCard.card_id];
    if (!a) continue;
    const target = currById.get(a.terminal);
    if (target) {
      renamed.push({ from: prevCard, to: target, method: a.method });
      absorbedFromPrev.add(prevCard.card_id);
    }
    // If the alias terminal isn't in curr, fall through to the normal
    // add/remove logic — the alias is dangling for this diff window.
  }

  for (const c of curr) {
    if (!prevById.has(c.card_id)) {
      // It's "new" unless it's the terminal of a rename we already accounted for.
      const isRenameTarget = renamed.some((r) => r.to.card_id === c.card_id);
      if (!isRenameTarget) added.push(c);
    }
  }

  for (const c of prev) {
    if (!currById.has(c.card_id) && !absorbedFromPrev.has(c.card_id)) {
      removed.push(c);
    }
  }

  return { added, removed, renamed };
}

// --- Field-only changes --------------------------------------------

// Fields we surface when they change between snapshots. Order matters
// for the display string the UI builds from `fields`.
const _COMPARED_FIELDS: Array<keyof CardMetadata> = [
  "title",
  "asset_type",
  "agency",
  "release_date",
  "incident_date",
  "incident_location",
  "redacted",
  "description",
  "asset_url",
  "asset_filename",
  "modal_image_url",
  "image_alt_text",
  "image_virin",
  "original_classification",
];

export interface FieldChange {
  card_id: string;
  fields: string[];
}

export function fieldOnlyChanges(prev: CardMetadata[], curr: CardMetadata[]): FieldChange[] {
  const prevById = new Map(prev.map((c) => [c.card_id, c]));
  const out: FieldChange[] = [];
  for (const c of curr) {
    const p = prevById.get(c.card_id);
    if (!p) continue; // present only in curr → that's an "added", handled elsewhere
    const fields: string[] = [];
    for (const f of _COMPARED_FIELDS) {
      if ((p as any)[f] !== (c as any)[f]) fields.push(f);
    }
    if (fields.length > 0) {
      out.push({ card_id: c.card_id, fields });
    }
  }
  return out;
}
