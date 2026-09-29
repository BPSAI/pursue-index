// Page title/text for /api/retrieve citations.
//
// The Worker used to parse the whole pages.json (~25 MB of bytes, then a
// UTF-16 string, then an object graph) to cite at most ~20 pages, which
// alone approached a cold isolate's 128 MB. It now reads the retrieval
// payload built by scripts/build_retrieve_rows.py:
//
//   /data/retrieve/rows.json               manifest: shards + titles file
//   /data/retrieve/rows-<start>-<sha>.json [[card_id, page, title, text] | null, ...]
//   /data/retrieve/titles-0-<sha>.json     [[card_id, title], ...]
//
// Shard row i is embed_index.json row i. Only the shards holding a query's
// rows are fetched, one at a time, and each is dropped once its rows are
// copied out, so a request holds at most one shard (~1 MB) at a time.

const BASE = "https://assets/data/retrieve/";

async function fetchJson(fetchFn, name) {
  const res = await fetchFn(BASE + name);
  if (!res.ok) throw new Error(`retrieve/${name} fetch failed: ${res.status}`);
  return JSON.parse(await res.text());
}

/** The shard manifest; small, loaded once per isolate by the caller. */
export async function loadRowsManifest(fetchFn) {
  const m = await fetchJson(fetchFn, "rows.json");
  if (!m || !Array.isArray(m.shards) || typeof m.n !== "number" || !m.titles?.path) {
    throw new Error("retrieve/rows.json: not a retrieval rows manifest");
  }
  return m;
}

/**
 * Records for the given embedding rows: Map<row, {card_id, page, title,
 * text}>. A row whose page record is missing is left out of the map.
 */
export async function loadRows(fetchFn, manifest, rowIds) {
  const wanted = [...new Set(rowIds)].sort((a, b) => a - b);
  const out = new Map();
  let w = 0;
  for (const shard of manifest.shards) {
    const end = shard.start + shard.count;
    while (w < wanted.length && wanted[w] < shard.start) w += 1;
    if (w >= wanted.length) break;
    if (wanted[w] >= end) continue;
    const rows = await fetchJson(fetchFn, shard.path);
    if (!Array.isArray(rows) || rows.length !== shard.count) {
      throw new Error(`retrieve/${shard.path}: expected ${shard.count} rows`);
    }
    for (; w < wanted.length && wanted[w] < end; w += 1) {
      const row = rows[wanted[w] - shard.start];
      if (!row) continue;
      const [card_id, page, title, text] = row;
      out.set(wanted[w], { card_id, page, title, text });
    }
  }
  return out;
}

/** Map<card_id, {card_id, title}> in first-page order, for the slug index. */
export async function loadTitles(fetchFn, manifest) {
  const pairs = await fetchJson(fetchFn, manifest.titles.path);
  return new Map(pairs.map(([card_id, title]) => [card_id, { card_id, title }]));
}
