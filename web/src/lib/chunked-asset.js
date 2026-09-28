/**
 * Chunk-aware loader for `web/public/data` payloads — the one reader every
 * consumer uses (browser islands, the Worker, Astro build-time readers).
 *
 * Cloudflare Workers refuses any single static asset over 25 MiB, so a
 * payload over the 24 MiB budget ships as ordered byte-range parts plus a
 * manifest next to it (written by `pursue_index.release.chunked_asset`):
 *
 *   pages-cleaned.json.chunks.json   { name, size, sha256, parts: [{ path, size }] }
 *   pages-cleaned.json.part-000-<sha12>.json
 *   pages-cleaned.json.part-001-<sha12>.json
 *
 * Part names are content-addressed (the first 12 hex digits of the part's
 * sha256) and readers only ever fetch the names a manifest lists, so a
 * manifest cannot be paired with another release's parts.
 *
 * A payload within budget keeps its URL and its manifest lists the whole
 * file as the only part. Readers fetch the manifest first, then the parts in
 * parallel, and concatenate bytes before decoding (a part boundary may fall
 * inside a UTF-8 character). With no manifest they fall back to the plain
 * URL, so a file published without one still loads.
 *
 * Plain JS (JSDoc-typed) so the Worker bundle and the Node test runner can
 * import it without a TypeScript step.
 */

export const MANIFEST_SUFFIX = ".chunks.json";

/** @typedef {{ path: string, size: number }} ChunkPart */
/** @typedef {{ name: string, size: number, sha256?: string, parts: ChunkPart[] }} ChunkManifest */
/** @typedef {(url: string) => Promise<Response>} FetchLike */
/** @typedef {{ existsSync: (p: string) => boolean, readFileSync: (p: string) => Uint8Array }} FsLike */

/** @param {string} url */
export function manifestUrl(url) {
  return url + MANIFEST_SUFFIX;
}

/** Sibling of `url` (or a filesystem path) named `name`. */
function sibling(url, name) {
  const cut = Math.max(url.lastIndexOf("/"), url.lastIndexOf("\\"));
  return url.slice(0, cut + 1) + name;
}

/**
 * Validate a parsed manifest; part paths must be bare sibling filenames.
 * @param {unknown} raw
 * @param {string} where
 * @returns {ChunkManifest}
 */
export function parseManifest(raw, where) {
  const m = /** @type {ChunkManifest} */ (raw);
  if (!m || typeof m !== "object" || !Array.isArray(m.parts) || typeof m.size !== "number") {
    throw new Error(`${where}: not a chunk manifest`);
  }
  for (const p of m.parts) {
    if (typeof p?.path !== "string" || !/^[^/\\]+$/.test(p.path) || p.path.startsWith(".")) {
      throw new Error(`${where}: bad part path ${JSON.stringify(p?.path)}`);
    }
  }
  // The manifest must describe the asset it sits next to...
  const base = where.slice(Math.max(where.lastIndexOf("/"), where.lastIndexOf("\\")) + 1);
  const asset = base.endsWith(MANIFEST_SUFFIX) ? base.slice(0, -MANIFEST_SUFFIX.length) : base;
  if (m.name !== asset) {
    throw new Error(`${where}: manifest names ${m.name}, expected ${asset}`);
  }
  // ...and name only that asset's parts, content-addressed and in order, so
  // a manifest can never be paired with another release's parts (their
  // names differ; a stale pairing 404s rather than mixing bytes).
  m.parts.forEach((p, i) => {
    if (m.parts.length === 1 ? p.path !== asset : !isPartName(asset, i, p.path)) {
      throw new Error(`${where}: part name ${p.path} is not the content-addressed name for part ${i}`);
    }
  });
  return m;
}

/**
 * `<name>.part-<NNN>-<12 hex of the part's sha256><ext>` — the name
 * `pursue_index.release.chunked_asset.part_name` writes.
 * @param {string} name
 * @param {number} index
 * @param {string} part
 */
export function isPartName(name, index, part) {
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  const prefix = `${name}.part-${String(index).padStart(3, "0")}-`;
  if (!part.startsWith(prefix) || !part.endsWith(ext)) return false;
  return /^[0-9a-f]{12}$/.test(part.slice(prefix.length, part.length - ext.length));
}

/**
 * Concatenate parts after checking each against the manifest.
 * @param {ChunkManifest} m
 * @param {Uint8Array[]} parts
 */
export function assembleParts(m, parts) {
  if (parts.length === 1 && m.parts.length === 1) {
    // A whole-file asset: hand back the part itself rather than a copy.
    if (parts[0].length !== m.size || m.parts[0].size !== m.size) {
      throw new Error(`${m.name}: size ${parts[0].length}, manifest says ${m.size}`);
    }
    return parts[0];
  }
  const out = new Uint8Array(m.size);
  let offset = 0;
  m.parts.forEach((p, i) => {
    const bytes = parts[i];
    if (bytes.length !== p.size) {
      throw new Error(`${m.name}: part ${p.path} size ${bytes.length}, manifest says ${p.size}`);
    }
    if (offset + bytes.length > m.size) {
      throw new Error(`${m.name}: parts exceed manifest size ${m.size}`);
    }
    out.set(bytes, offset);
    offset += bytes.length;
  });
  if (offset !== m.size) {
    throw new Error(`${m.name}: parts total size ${offset}, manifest says ${m.size}`);
  }
  return out;
}

/**
 * Bytes of the asset at `url`, reassembled if chunked; `null` when neither a
 * manifest nor the plain file exists (404). Any other failure throws.
 * @param {string} url
 * @param {FetchLike} [fetchFn]
 * @returns {Promise<Uint8Array | null>}
 */
export async function loadAssetBytes(url, fetchFn = (u) => fetch(u)) {
  const mres = await fetchFn(manifestUrl(url));
  if (mres.status === 404) {
    const res = await fetchFn(url);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`fetch ${url}: ${res.status}`);
    return new Uint8Array(await res.arrayBuffer());
  }
  if (!mres.ok) throw new Error(`fetch ${manifestUrl(url)}: ${mres.status}`);
  const m = parseManifest(await mres.json(), manifestUrl(url));
  const parts = await Promise.all(
    m.parts.map(async (p) => {
      const partUrl = sibling(url, p.path);
      const res = await fetchFn(partUrl);
      if (!res.ok) throw new Error(`fetch ${partUrl}: ${res.status}`);
      return new Uint8Array(await res.arrayBuffer());
    }),
  );
  return assembleParts(m, parts);
}

/** @typedef {{ update: (chunk: Uint8Array) => void | Promise<void>, digestHex: () => Promise<string> }} Digest */

/**
 * Streaming SHA-256 where the runtime has one: `crypto.DigestStream` in
 * Workers. Elsewhere (browsers, Node) returns null and callers fall back to
 * size checks; tests inject their own digest.
 * @returns {Digest | null}
 */
export function streamingSha256() {
  const DigestStream = /** @type {any} */ (globalThis.crypto)?.DigestStream;
  if (typeof DigestStream !== "function") return null;
  const stream = new DigestStream("SHA-256");
  const writer = stream.getWriter();
  return {
    update: (chunk) => writer.write(chunk),
    digestHex: async () => {
      await writer.close();
      const bytes = new Uint8Array(await stream.digest);
      return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    },
  };
}

/**
 * Stream the asset at `url` to `onChunk` in byte order, one network chunk at
 * a time: parts are fetched sequentially and read from their response
 * streams, so neither a whole part nor the assembled payload is ever held.
 * Checks each part's size against the manifest, the total, and (when the
 * manifest carries one and a streaming digest exists) the whole-file
 * sha256. Resolves `{ size }`, or `null` when neither a manifest nor the
 * plain file exists.
 * @param {string} url
 * @param {FetchLike} fetchFn
 * @param {(chunk: Uint8Array) => void} onChunk
 * @param {{ createDigest?: () => Digest | null }} [opts]
 */
export async function forEachAssetChunk(url, fetchFn, onChunk, opts = {}) {
  const { createDigest = streamingSha256 } = opts;
  const mres = await fetchFn(manifestUrl(url));
  /** @type {Array<{ url: string, name: string, size: number | null }>} */
  let sources = [{ url, name: url.slice(url.lastIndexOf("/") + 1), size: null }];
  let manifest = null;
  if (mres.status !== 404) {
    if (!mres.ok) throw new Error(`fetch ${manifestUrl(url)}: ${mres.status}`);
    manifest = parseManifest(await mres.json(), manifestUrl(url));
    sources = manifest.parts.map((p) => ({ url: sibling(url, p.path), name: p.path, size: p.size }));
  }
  const digest = manifest?.sha256 ? createDigest() : null;
  let total = 0;
  for (const src of sources) {
    const res = await fetchFn(src.url);
    if (!manifest && res.status === 404) return null;
    if (!res.ok || !res.body) throw new Error(`fetch ${src.url}: ${res.status}`);
    const reader = res.body.getReader();
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      got += value.length;
      if (src.size !== null && got > src.size) break;
      if (digest) await digest.update(value);
      onChunk(value);
    }
    if (src.size !== null && got !== src.size) {
      await reader.cancel().catch(() => {});
      const streamed = got > src.size ? `more than ${src.size}` : String(got);
      throw new Error(`${src.name}: streamed size ${streamed} bytes, manifest says ${src.size}`);
    }
    total += got;
  }
  if (manifest && total !== manifest.size) {
    throw new Error(`${manifest.name}: parts total size ${total}, manifest says ${manifest.size}`);
  }
  if (digest && manifest && (await digest.digestHex()) !== manifest.sha256) {
    throw new Error(`${manifest.name}: sha256 of the streamed bytes does not match the manifest`);
  }
  return { size: total };
}

/**
 * Parsed JSON of the asset at `url`; `null` when it does not exist.
 * @param {string} url
 * @param {FetchLike} [fetchFn]
 */
export async function loadAssetJson(url, fetchFn) {
  const bytes = await loadAssetBytes(url, fetchFn);
  return bytes === null ? null : JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * Build-time twin of `loadAssetBytes` over the filesystem. `fs` is injected
 * so this module stays importable from browser bundles.
 * @param {string} path
 * @param {FsLike} fs
 * @returns {Uint8Array | null}
 */
export function readAssetSync(path, fs) {
  const mpath = manifestUrl(path);
  if (fs.existsSync(mpath)) {
    const m = parseManifest(
      JSON.parse(new TextDecoder().decode(fs.readFileSync(mpath))),
      mpath,
    );
    return assembleParts(m, m.parts.map((p) => fs.readFileSync(sibling(path, p.path))));
  }
  if (!fs.existsSync(path)) return null;
  return fs.readFileSync(path);
}

/**
 * @param {string} path
 * @param {FsLike} fs
 */
export function readAssetJsonSync(path, fs) {
  const bytes = readAssetSync(path, fs);
  return bytes === null ? null : JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * @param {string} path
 * @param {FsLike} fs
 */
export function assetExistsSync(path, fs) {
  return fs.existsSync(manifestUrl(path)) || fs.existsSync(path);
}
