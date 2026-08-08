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
 *   pairRowsByCardId / unpairedRowEntries — re-exported from `row-pairing.ts`
 */

import type { AliasEntry, CardMetadata } from "../data/types.ts";
import { pairRowsByCardId } from "./row-pairing.ts";

// Re-exported so the /diff island and its tests keep a single import
// site for the diff surface; the pairing rules themselves live in
// `row-pairing.ts`.
export {
  describeUnpairedRow,
  pairRowsByCardId,
  unpairedRowEntries,
  type CardIdPairing,
  type RowPair,
  type UnpairedRow,
  type UnpairedRowDisplay,
} from "./row-pairing.ts";

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

// --- Snapshot index normalization -----------------------------------

export interface SnapshotIndexMeta {
  fetched_at?: string;
  card_count?: number;
}

export interface NormalizedSnapshotIndex {
  /** Chronologically-ordered snapshot filenames (the legacy shape). */
  filenames: string[];
  /** filename → label metadata, when the enriched index supplies it. */
  meta: Record<string, SnapshotIndexMeta>;
}

/**
 * Accept either the legacy bare ``string[]`` snapshot index or the
 * enriched ``Array<{filename, fetched_at?, card_count?}>`` form and
 * return both the ordered filename list (so every existing consumer
 * keeps working unchanged) and a filename→meta map (so the selectors
 * can label a snapshot without lazily fetching its full manifest).
 *
 * Tolerant by construction: a deploy where the published index is
 * still the old flat list yields empty meta (selectors fall back to
 * the loaded-manifest count), and malformed entries are dropped rather
 * than throwing — this runs client-side against fetched JSON.
 */
export function normalizeSnapshotIndex(raw: unknown): NormalizedSnapshotIndex {
  const filenames: string[] = [];
  const meta: Record<string, SnapshotIndexMeta> = {};
  if (!Array.isArray(raw)) return { filenames, meta };
  for (const entry of raw) {
    if (typeof entry === "string") {
      if (entry) filenames.push(entry);
      continue;
    }
    if (entry && typeof entry === "object") {
      const filename = (entry as { filename?: unknown }).filename;
      if (typeof filename !== "string" || !filename) continue;
      filenames.push(filename);
      const e = entry as { fetched_at?: unknown; card_count?: unknown };
      meta[filename] = {
        fetched_at: typeof e.fetched_at === "string" ? e.fetched_at : undefined,
        card_count: typeof e.card_count === "number" ? e.card_count : undefined,
      };
    }
  }
  return { filenames, meta };
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

/**
 * Recency-aware default pair, accounting for ``latest.json`` (the @current
 * sentinel) relative to the snapshots.
 *
 * The snapshot index is chronological oldest→newest by ``fetched_at``;
 * ``currentFetchedAt`` is latest.json's own ``fetched_at``. Before Sprint 6 a
 * scrape made latest.json the newest state, so "append @current as newest" held.
 * The Sprint 6 poll/snapshot job now writes a snapshot the moment a tranche is
 * detected — BEFORE it is ingested/promoted — so the newest snapshot can be
 * newer than latest.json. Naively treating @current as newest then inverts the
 * default diff (the incoming cards render as "removed").
 *
 * Order by recency so the latest tranche always reads as ADDITIONS:
 *   - @current strictly newer than the newest snapshot → (newest snapshot → @current)
 *   - otherwise — a pending un-ingested tranche (newest snapshot ahead of
 *     latest.json), OR the normal post-promotion case where @current equals the
 *     newest snapshot — default to the two newest snapshots.
 */
export function selectDefaultPairWithCurrent(
  index: string[],
  meta: Record<string, SnapshotIndexMeta>,
  currentFetchedAt: string | undefined,
  currentSentinel: string,
): { from: string | null; to: string | null } {
  if (index.length === 0) return { from: null, to: currentSentinel };
  const newest = index[index.length - 1];
  const newestAt = meta[newest]?.fetched_at;
  // Compare by instant, not lexically: fetched_at is normally UTC ``Z`` but a
  // timezone offset (``+02:00``) or differing precision would silently mis-order
  // a string compare — and direction is exactly what this selector exists to fix.
  const currentNewer =
    !!currentFetchedAt && (!newestAt || tsMillis(currentFetchedAt) > tsMillis(newestAt));
  if (currentNewer) {
    return { from: newest, to: currentSentinel };
  }
  // @current is older-or-equal (a pending un-ingested tranche, or post-promotion
  // equality). With ≥2 snapshots the two newest read old→new. With a single
  // snapshot there is no second one to pair, so pair against @current rather than
  // returning a null ``from`` (which leaves DiffIsland stuck loading): a pending
  // tranche reads @current→snapshot (additions); otherwise snapshot→@current.
  if (index.length === 1) {
    const snapshotNewer =
      !!currentFetchedAt && !!newestAt && tsMillis(newestAt) > tsMillis(currentFetchedAt);
    return snapshotNewer
      ? { from: currentSentinel, to: newest }
      : { from: newest, to: currentSentinel };
  }
  return selectDefaultPair(index);
}

/** Parse an ISO-8601 timestamp to epoch millis for instant comparison. */
function tsMillis(ts: string): number {
  return Date.parse(ts);
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

// --- Snapshot option formatting (upstream vs. our promoted state) ---
//
// The /diff selectors must never render `latest.json` (our promoted state)
// in the same `sha8 · date · count` grammar as a real upstream (war.gov)
// snapshot — CURRENT carrying today's date and a matching card count reads
// as if the government dropped a second manifest. It didn't; we promoted
// one. These helpers keep upstream snapshots and the single promoted-state
// entry structurally separate and give the promoted entry a label that
// names its source instead of carrying its own standalone date.

/** Strip the `.json` suffix and truncate to the sha8 prefix used throughout the UI. */
export function shaPrefix(filename: string): string {
  return filename.replace(/\.json$/i, "").slice(0, 8);
}

/**
 * Format an ISO timestamp with minute-precision time, not just a date.
 * War.gov genuinely double-drops on the same day (2026-06-12 has two
 * snapshots); a date-only label makes them indistinguishable without
 * reading sha prefixes.
 */
export function formatSnapshotTimestamp(iso?: string): string {
  if (!iso) return "—";
  return `${iso.slice(0, 16).replace("T", " ")}Z`;
}

export interface SnapshotOptionMeta {
  filename: string;
  fetched_at?: string;
  card_count?: number;
}

/** The synthetic `@current` entry, relabelled as our promoted state. */
export interface PromotedStateOption {
  filename: string;
  fetched_at?: string;
  card_count?: number;
  /** The upstream snapshot filename `@current` was promoted from, or null if unresolved. */
  promotedFrom: string | null;
}

export interface GroupedSnapshotOptions {
  upstream: SnapshotOptionMeta[];
  promoted: PromotedStateOption;
}

/**
 * Find the upstream snapshot `@current` was promoted from. Snapshot
 * filenames are `${csv_sha256}.json` (see `poll_snapshot.py`), so the
 * match is exact identity — never a heuristic on date or card count, both
 * of which can coincide with an unrelated snapshot.
 */
export function findPromotedFromFilename(
  index: string[],
  currentCsvSha256: string | undefined,
): string | null {
  if (!currentCsvSha256) return null;
  return index.find((f) => f.replace(/\.json$/i, "") === currentCsvSha256) ?? null;
}

/**
 * Build the grouped option list for the /diff selectors: one upstream
 * (war.gov) entry per index filename, plus exactly one promoted-state
 * entry for `@current` — never conflated into a single flat list the way
 * the old `[...index, @current]` array was.
 */
export function buildGroupedSnapshotOptions(
  index: string[],
  meta: Record<string, SnapshotIndexMeta>,
  current: { fetched_at?: string; card_count?: number; csv_sha256?: string },
  currentSentinel: string,
): GroupedSnapshotOptions {
  const upstream = index.map((f) => ({
    filename: f,
    fetched_at: meta[f]?.fetched_at,
    card_count: meta[f]?.card_count,
  }));
  return {
    upstream,
    promoted: {
      filename: currentSentinel,
      fetched_at: current.fetched_at,
      card_count: current.card_count,
      promotedFrom: findPromotedFromFilename(index, current.csv_sha256),
    },
  };
}

/** Label grammar for an upstream (war.gov) snapshot option: `sha8 · date time · N cards`. */
export function formatUpstreamSnapshotLabel(o: SnapshotOptionMeta): string {
  const count = o.card_count != null ? `${o.card_count} cards` : "?? cards";
  return `${shaPrefix(o.filename)} · ${formatSnapshotTimestamp(o.fetched_at)} · ${count}`;
}

/**
 * Label grammar for the promoted-state option: names the upstream snapshot
 * it was promoted from instead of carrying its own standalone date, so it
 * never reads as a second war.gov drop.
 */
export function formatPromotedStateLabel(o: PromotedStateOption): string {
  const from = o.promotedFrom ? shaPrefix(o.promotedFrom) : "unresolved";
  const count = o.card_count != null ? `${o.card_count} cards` : "?? cards";
  return `PROMOTED STATE · from ${from} · ${count}`;
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

  // Row-level churn within a card_id present on both sides: a duplicate
  // id (PDF row + VID row(s)) can lose or gain individual rows upstream
  // while the id itself survives. Map.has(card_id) above is a set check
  // and is blind to that — the id being present on both sides is enough
  // to skip it entirely, so the dropped/added rows vanished. Reuse
  // pairRowsByCardId's `unpaired` — the SAME stable row key T47.1
  // established — so a row that pairs (including via the 1-vs-1
  // leftover rule) is never double-counted here as both added and
  // removed.
  const { unpaired } = pairRowsByCardId(prev, curr);
  for (const u of unpaired) {
    if (absorbedFromPrev.has(u.card_id)) continue; // rows of a renamed-away id
    if (u.side === "curr") added.push(u.row);
    else removed.push(u.row);
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
  "featured",
  "description",
  "asset_url",
  "asset_filename",
  "modal_image_url",
  "image_alt_text",
  "image_virin",
  "original_classification",
  // The two row-identity keys. They are also the fields rows bucket by
  // (see row-pairing.ts), so a mutation of either moves a row into the
  // 1-vs-1 leftover pass and pairs there — which means it reaches this
  // comparison rather than showing up as an unpaired row. Without them
  // here an upstream retitle or video-id change renders as no change at
  // all on this page while the committed receipt reports it.
  "video_title",
  "dvids_video_id",
];

// Boolean fields are compared by truthiness so a snapshot predating the
// field (value absent → undefined) reads equal to an explicit `false`.
// Without this, adding `featured` would flag every non-featured card as
// "changed" the first time a post-column snapshot is diffed against a
// pre-column one.
const _BOOLEAN_FIELDS = new Set<keyof CardMetadata>(["redacted", "featured"]);

export interface FieldChange {
  card_id: string;
  fields: string[];
}

export function fieldOnlyChanges(prev: CardMetadata[], curr: CardMetadata[]): FieldChange[] {
  const { pairs } = pairRowsByCardId(prev, curr);
  // A card_id may contribute several pairs (PDF + VID rows); union the
  // changed fields per card_id, preserving _COMPARED_FIELDS order and
  // first-seen order across pairs, so the UI shows one entry per card.
  const changedByCard = new Map<string, string[]>();
  for (const { card_id, prev: p, curr: c } of pairs) {
    for (const f of _COMPARED_FIELDS) {
      const pv = (p as any)[f];
      const cv = (c as any)[f];
      const changed = _BOOLEAN_FIELDS.has(f)
        ? Boolean(pv) !== Boolean(cv)
        : pv !== cv;
      if (!changed) continue;
      const fields = changedByCard.get(card_id) ?? [];
      if (!fields.includes(f)) fields.push(f);
      changedByCard.set(card_id, fields);
    }
  }
  const out: FieldChange[] = [];
  for (const [card_id, fields] of changedByCard) {
    if (fields.length > 0) out.push({ card_id, fields });
  }
  return out;
}
