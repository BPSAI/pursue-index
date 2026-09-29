// Test helper: publish the Worker retrieval text payload
// (scripts/build_retrieve_rows.py's `data/retrieve/` layout) for a fixture
// index + pages list into a Map of `/data/`-relative name -> body.

export function publishRetrieveRows(files, indexPages, pagesArr, { rowsPerShard = 2 } = {}) {
  const byKey = new Map(pagesArr.map((p) => [`${p.card_id}-p${p.page}`, p]));
  const rows = indexPages.map(([card_id, page]) => {
    const rec = byKey.get(`${card_id}-p${page}`);
    return rec ? [card_id, page, rec.title ?? "", rec.text ?? ""] : null;
  });
  const shards = [];
  for (let start = 0; start < rows.length; start += rowsPerShard) {
    const part = rows.slice(start, start + rowsPerShard);
    const path = `rows-${start}-${String(start).padStart(12, "0")}.json`;
    const body = JSON.stringify(part);
    files.set(`retrieve/${path}`, body);
    shards.push({ start, count: part.length, path, size: body.length });
  }
  const titles = [];
  const seen = new Set();
  for (const p of pagesArr) {
    if (seen.has(p.card_id)) continue;
    seen.add(p.card_id);
    titles.push([p.card_id, p.title ?? ""]);
  }
  const titlesBody = JSON.stringify(titles);
  files.set("retrieve/titles-0-000000000000.json", titlesBody);
  files.set(
    "retrieve/rows.json",
    JSON.stringify({
      schema: "pursue-retrieve-rows/1",
      n: rows.length,
      shards,
      titles: { path: "titles-0-000000000000.json", size: titlesBody.length },
    }),
  );
  return files;
}

/** An ASSETS binding over `files`, logging each fetched name. */
export function filesAssets(files, log = []) {
  return {
    fetch: async (u) => {
      const name = String(u).split("/data/")[1];
      log.push(name);
      return files.has(name)
        ? new Response(files.get(name), { status: 200 })
        : new Response("not found", { status: 404 });
    },
  };
}

/**
 * Response for a `/data/retrieve/...` URL over the payload published from
 * `indexPages` + `pagesArr`, or null for any other URL — a drop-in branch
 * for hand-rolled ASSETS mocks.
 */
export function retrieveRowsResponse(url, indexPages, pagesArr) {
  const name = String(url).split("/data/")[1] ?? "";
  if (!name.startsWith("retrieve/")) return null;
  const files = publishRetrieveRows(new Map(), indexPages, pagesArr);
  return files.has(name)
    ? new Response(files.get(name), { status: 200 })
    : new Response("not found", { status: 404 });
}
