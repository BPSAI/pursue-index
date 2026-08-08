/**
 * Row pairing for the /diff page.
 *
 * A card_id can be backed by more than one manifest row: 9 ids in the
 * manifest carry a PDF row plus one or more VID rows, and that is the
 * upstream CSV's real shape — the rows are never deduped, collapsed or
 * normalized anywhere in this codebase. Before two snapshots can be
 * compared field-by-field, each prev row has to be matched to the curr
 * row that represents the same thing.
 *
 * Pairing rules:
 *
 *   1. Rows only ever pair inside the same card_id group.
 *   2. Inside a group, rows bucket by ``(dvids_video_id, video_title)``.
 *      dvids_video_id distinguishes rows that are otherwise identical
 *      (the three VID rows under ea029a05470b8f4e share asset_url and
 *      video_title). It does NOT separate a PDF row from its VID
 *      sibling: in all 9 duplicate groups the PDF row carries the same
 *      dvids_video_id as the VID row (3746998b8c506e5c's PDF row
 *      carries dvids_video_id 1006080, as does its VID row). What
 *      buckets those two apart is video_title, which upstream sets on
 *      the VID row and leaves empty on the PDF row.
 *   3. A change to a keying field is itself reported by the diff (neither
 *      is in the diff's skip set — see `DIFF_SKIP_FIELDS` in
 *      diff-helpers.ts), and a change to any other
 *      field (asset_type, asset_url, title, …) cannot prevent its own
 *      row from pairing.
 *   4. If bucketing leaves exactly one prev row and one curr row over in
 *      a group AND the two carry the same asset_type, they are paired: a
 *      mutation of a keying field is a change to report, not a reason to
 *      stop reporting. Leftovers of differing asset_type are a
 *      withdrawal plus an addition, not one mutated row.
 *   5. Anything still unmatched is returned as an unpaired row, tagged
 *      with its side, so a row appearing or disappearing under an
 *      existing card_id is visible rather than dropped.
 *
 * What the asset_type gate in rule 4 does and does not cover: it applies
 * only to the leftover pass, where the two candidates' identity keys
 * DIFFER and asset_type is the last thing left to match on. It is not a
 * guard against cross-type comparison in general, and rule 2 does not
 * provide one either — rows pair inside a bucket because they share
 * `(dvids_video_id, video_title)`, and asset_type is not consulted there.
 * So two rows of different asset_type that share an identity key (a lone
 * PDF row and a lone VID row under one card_id, both carrying the same
 * dvids_video_id and no video_title) do pair, and the field diff reports
 * asset_type as the changed field.
 *
 * That is deliberate, not a leak: it is how an asset_type mutation on one
 * upstream identity gets reported at all. Splitting such a pair into a
 * withdrawal and an addition would say a row left and another arrived
 * without ever naming the field that moved, and would stop reporting the
 * real VID→AUD reclassifications the shared fixture pins. In the 9
 * duplicate groups a PDF row and its VID sibling do NOT collide this way:
 * they share a dvids_video_id but bucket apart on video_title, which
 * upstream sets on the VID row and leaves empty on the PDF row.
 *
 * Row order within a group carries no meaning upstream, so pairing never
 * depends on it: reordering identical rows produces no diff.
 */

import type { CardMetadata } from "../data/types.ts";

/** A prev↔curr row pairing within a single card_id group. */
export interface RowPair {
  card_id: string;
  prev: CardMetadata;
  curr: CardMetadata;
}

/** A manifest row that had no counterpart on the other side of the diff. */
export interface UnpairedRow {
  card_id: string;
  side: "prev" | "curr";
  row: CardMetadata;
}

export interface CardIdPairing {
  pairs: RowPair[];
  unpaired: UnpairedRow[];
}

/** Group manifest rows by card_id, preserving each id's row order. */
export function groupByCardId(rows: CardMetadata[]): Map<string, CardMetadata[]> {
  const groups = new Map<string, CardMetadata[]>();
  for (const c of rows) {
    const g = groups.get(c.card_id);
    if (g) g.push(c);
    else groups.set(c.card_id, [c]);
  }
  return groups;
}

/**
 * Bucket key for pairing rows *within* a card_id group.
 *
 * The two keying fields are reported by the field diff like any other
 * (neither is in the diff's skip set); a mutation of one moves its row into
 * the 1-vs-1 leftover pass, which pairs it so the mutation is reported
 * rather than swallowed. A change to any other field cannot move a row
 * out of its bucket at all (see rule 3 above).
 */
export function rowIdentityKey(c: CardMetadata): string {
  return JSON.stringify([c.dvids_video_id ?? null, c.video_title ?? null]);
}

function bucketByKey(rows: CardMetadata[]): Map<string, CardMetadata[]> {
  const buckets = new Map<string, CardMetadata[]>();
  for (const c of rows) {
    const k = rowIdentityKey(c);
    const b = buckets.get(k);
    if (b) b.push(c);
    else buckets.set(k, [c]);
  }
  return buckets;
}

/** Pair one card_id's rows: bucket by key, then the 1-vs-1 leftover rule. */
function pairGroup(
  cardId: string,
  prevRows: CardMetadata[],
  currRows: CardMetadata[],
  pairs: RowPair[],
  unpaired: UnpairedRow[],
): void {
  const prevBuckets = bucketByKey(prevRows);
  const currBuckets = bucketByKey(currRows);
  const leftoverPrev: CardMetadata[] = [];
  const leftoverCurr: CardMetadata[] = [];
  for (const key of new Set([...prevBuckets.keys(), ...currBuckets.keys()])) {
    const p = prevBuckets.get(key) ?? [];
    const c = currBuckets.get(key) ?? [];
    const n = Math.min(p.length, c.length);
    for (let i = 0; i < n; i++) pairs.push({ card_id: cardId, prev: p[i], curr: c[i] });
    leftoverPrev.push(...p.slice(n));
    leftoverCurr.push(...c.slice(n));
  }
  // Exactly one leftover on each side, both of the same asset_type, is
  // unambiguous: same row, mutated keying field. More than one on either
  // side is ambiguous, and leftovers of different asset_types are a
  // withdrawal plus an addition, not one mutated row — those are reported
  // as unpaired rather than matched by guesswork.
  if (
    leftoverPrev.length === 1 &&
    leftoverCurr.length === 1 &&
    leftoverPrev[0].asset_type === leftoverCurr[0].asset_type
  ) {
    pairs.push({ card_id: cardId, prev: leftoverPrev[0], curr: leftoverCurr[0] });
    return;
  }
  for (const row of leftoverPrev) unpaired.push({ card_id: cardId, side: "prev", row });
  for (const row of leftoverCurr) unpaired.push({ card_id: cardId, side: "curr", row });
}

/**
 * Pair rows that share a card_id across two snapshots.
 *
 * card_ids present on only one side are NOT emitted here: those are
 * add/remove events (see ``diffWithAliases``), not row-level churn.
 */
export function pairRowsByCardId(prev: CardMetadata[], curr: CardMetadata[]): CardIdPairing {
  const prevGroups = groupByCardId(prev);
  const currGroups = groupByCardId(curr);
  const pairs: RowPair[] = [];
  const unpaired: UnpairedRow[] = [];
  for (const [cardId, prevRows] of prevGroups) {
    const currRows = currGroups.get(cardId);
    if (!currRows) continue; // whole card_id absent from curr → a removal
    pairGroup(cardId, prevRows, currRows, pairs, unpaired);
  }
  return { pairs, unpaired };
}

/**
 * The unpaired rows of a diff, in card_id order — the rows an existing
 * card_id gained or lost upstream. Rendered as its own section on /diff;
 * without it a manifest that adds a fourth video to a card that already
 * has three shows no change at all.
 */
export function unpairedRowEntries(
  prev: CardMetadata[],
  curr: CardMetadata[],
): UnpairedRow[] {
  const { unpaired } = pairRowsByCardId(prev, curr);
  return [...unpaired].sort(
    (a, b) => a.card_id.localeCompare(b.card_id) || a.side.localeCompare(b.side),
  );
}

/** Render-ready description of one unpaired row for the /diff page. */
export interface UnpairedRowDisplay {
  cardId: string;
  /** "ADDED" for a row only in the newer snapshot, "WITHDRAWN" for one only in the older. */
  verb: "ADDED" | "WITHDRAWN";
  symbol: "+" | "−";
  assetType: string;
  title: string;
  /** Identifying detail: the upstream video id on a video/audio row, else the asset filename or URL. */
  detail: string;
}

/** Asset types whose rows the upstream dvids_video_id actually identifies. */
const _DVIDS_ASSET_TYPES = new Set(["VID", "AUD"]);

export function describeUnpairedRow(entry: UnpairedRow): UnpairedRowDisplay {
  const { row } = entry;
  // A PDF row in a duplicate group carries its VID sibling's
  // dvids_video_id (see the pairing rules above), so keying this on the
  // field alone labelled document rows with a video's identifier.
  //
  // Site behaviour only, and deliberately narrower than the receipt: this
  // picks the ONE detail a reader should identify the row by, and on a PDF
  // row that is not a video id. The tranche receipt still prints the row's
  // dvids_video_id in its own labelled column, where the column header says
  // what the value is and no such confusion is possible. Suppressing it
  // here is not hiding the field — do not "fix" the two into agreement.
  const detail =
    row.dvids_video_id && _DVIDS_ASSET_TYPES.has(row.asset_type)
      ? `dvids ${row.dvids_video_id}`
      : (row.asset_filename ?? row.asset_url ?? row.asset_type ?? "row");
  return {
    cardId: entry.card_id,
    verb: entry.side === "curr" ? "ADDED" : "WITHDRAWN",
    symbol: entry.side === "curr" ? "+" : "−",
    assetType: row.asset_type,
    title: row.title,
    detail,
  };
}
