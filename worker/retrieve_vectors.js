// Float16 corpus vectors for /api/retrieve.
//
// `embeddings.bin` ships n*dim little-endian float16 values. Decoding them
// to a Float32Array doubles their footprint (14,480 x 1,024 rows: ~59 MB
// instead of ~30 MB), which on its own is close to half a Workers isolate's
// 128 MB. So the Worker keeps the raw float16 bits in a Uint16Array and
// scores against them through a 65,536-entry Float32 lookup table (256 KB)
// plus per-row norms computed once at load. The table holds exactly the
// values the float32 decode produced, and dot products and norms accumulate
// in the same order and precision, so scores match the float32 path.

import { forEachAssetChunk } from "../web/src/lib/chunked-asset.js";
import { normalizeVector } from "./retrieve_math.js";

export function halfToFloat(h) {
  const sign = (h & 0x8000) >> 15;
  const exp = (h & 0x7c00) >> 10;
  const frac = h & 0x03ff;
  if (exp === 0) {
    if (frac === 0) return sign ? -0 : 0;
    // subnormal
    return (sign ? -1 : 1) * (frac / 1024) * Math.pow(2, -14);
  }
  if (exp === 0x1f) {
    return frac === 0 ? (sign ? -Infinity : Infinity) : NaN;
  }
  return (sign ? -1 : 1) * (1 + frac / 1024) * Math.pow(2, exp - 15);
}

/** Decode a Float16 buffer to Float32. */
export function float16ToFloat32(buf) {
  const u16 = new Uint16Array(buf);
  const out = new Float32Array(u16.length);
  for (let i = 0; i < u16.length; i += 1) out[i] = halfToFloat(u16[i]);
  return out;
}

let _lut = null;

/** Float32 value of every float16 bit pattern; built once per isolate. */
export function float16Lut() {
  if (!_lut) {
    _lut = new Float32Array(65536);
    for (let h = 0; h < 65536; h += 1) _lut[h] = halfToFloat(h);
  }
  return _lut;
}

/**
 * Stream a little-endian float16 payload into one preallocated Uint16Array
 * of `count` values, copying bytes as they arrive: parts are read
 * sequentially from their response streams (see forEachAssetChunk), so no
 * part buffer or assembled payload is ever held. Resolves null when the
 * asset does not exist; throws when its size is not exactly `count * 2`.
 * Workers (and every platform Node runs on) are little-endian, so the
 * byte view of the Uint16Array is the file's own layout.
 */
export async function loadFloat16Asset(url, fetchFn, count, opts) {
  const out = new Uint16Array(count);
  const bytes = new Uint8Array(out.buffer);
  const name = url.slice(url.lastIndexOf("/") + 1);
  let at = 0;
  const res = await forEachAssetChunk(
    url,
    fetchFn,
    (chunk) => {
      if (at + chunk.length > bytes.length) {
        throw new Error(`${name} holds more than ${bytes.length} bytes; the index expects exactly that`);
      }
      bytes.set(chunk, at);
      at += chunk.length;
    },
    opts,
  );
  if (res === null) return null;
  if (at !== bytes.length) {
    throw new Error(`${name} holds ${res.size} bytes; the index expects ${bytes.length}`);
  }
  return out;
}

/** Per-row sum of squares, as the float32 path accumulates it (float64). */
export function rowNorms(u16, n, dim, lut) {
  const out = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    let mag = 0;
    const base = i * dim;
    for (let j = 0; j < dim; j += 1) {
      const v = lut[u16[base + j]];
      mag += v * v;
    }
    out[i] = Math.sqrt(mag);
  }
  return out;
}

/**
 * Top-k cosine similarity of a float32 `query` against float16 rows.
 * `norms` comes from `rowNorms`. Returns [{index, score}] sorted by score
 * descending, ties in row order — the same result `cosineTopK` gives over
 * the decoded Float32Array, without the full-corpus sort.
 */
export function cosineTopKF16(query, u16, norms, lut, k, n) {
  const dim = query.length;
  const q = normalizeVector(query);
  const top = [];
  const want = Math.min(k, n);
  for (let i = 0; i < n; i += 1) {
    let dot = 0;
    const base = i * dim;
    for (let j = 0; j < dim; j += 1) dot += q[j] * lut[u16[base + j]];
    const score = dot / (norms[i] === 0 ? 1 : norms[i]);
    if (top.length === want && !(score > top[want - 1].score)) continue;
    // Insert after every equal score so earlier rows win ties.
    let at = top.length;
    while (at > 0 && top[at - 1].score < score) at -= 1;
    top.splice(at, 0, { index: i, score });
    if (top.length > want) top.pop();
  }
  return top;
}
