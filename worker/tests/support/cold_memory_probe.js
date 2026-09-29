// Cold-isolate memory probe for /api/retrieve. Run in a child process:
//
//   node --expose-gc tests/support/cold_memory_probe.js [dataDir]
//
// Serves the committed web/public/data payloads through a fake ASSETS
// binding (streamed from disk, like the Workers static-asset pipeline),
// then runs two concurrent cold retrievals (PROBE_CONCURRENCY) at k=20 with a literal slug in
// the query, so every lane loads. Live memory (V8 heap + external/array
// buffers, after a forced GC) is sampled at every point where the cold
// path holds the most at once:
//   - after each TextDecoder.decode (source bytes + decoded string live),
//   - after each JSON.parse (source string + parsed graph live),
//   - every few streamed network chunks, and on a 1 ms timer.
// Prints one JSON line: { baseline, peak, peakDelta, passages }.

import fs from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";
import { fileURLToPath } from "node:url";

import { retrievePassages, _resetCaches } from "../../retrieve.js";

if (typeof globalThis.gc !== "function") {
  throw new Error("run with --expose-gc");
}

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = path.resolve(process.argv[2] || path.join(here, "../../../web/public/data"));

function live() {
  globalThis.gc();
  const m = process.memoryUsage();
  return m.heapUsed + m.external;
}

let peak = 0;
function sample() {
  const now = live();
  if (now > peak) peak = now;
}

// Query vector: a stored corpus row (no network call), read straight from
// the first embeddings part before the baseline is taken.
function storedQueryVector(row) {
  const index = JSON.parse(fs.readFileSync(path.join(dataDir, "embed_index.json"), "utf8"));
  const manifest = JSON.parse(fs.readFileSync(path.join(dataDir, "embeddings.bin.chunks.json"), "utf8"));
  const fd = fs.openSync(path.join(dataDir, manifest.parts[0].path), "r");
  const buf = Buffer.alloc(index.dim * 2);
  fs.readSync(fd, buf, 0, buf.length, row * index.dim * 2);
  fs.closeSync(fd);
  const out = new Float32Array(index.dim);
  for (let j = 0; j < index.dim; j += 1) out[j] = halfToFloat(buf.readUInt16LE(j * 2));
  return out;
}

function halfToFloat(h) {
  const s = h & 0x8000 ? -1 : 1;
  const e = (h & 0x7c00) >> 10;
  const f = h & 0x03ff;
  if (e === 0) return s * (f / 1024) * 2 ** -14;
  if (e === 0x1f) return f ? NaN : s * Infinity;
  return s * (1 + f / 1024) * 2 ** (e - 15);
}

function fileResponse(file) {
  let n = 0;
  const sampling = new TransformStream({
    transform(chunk, controller) {
      n += 1;
      if (n % 8 === 0) sample();
      controller.enqueue(chunk);
    },
  });
  const body = Readable.toWeb(fs.createReadStream(file, { highWaterMark: 64 * 1024 }));
  return new Response(body.pipeThrough(sampling), { status: 200 });
}

const ASSETS = {
  async fetch(u) {
    const rel = decodeURIComponent(new URL(String(u)).pathname.replace(/^\/data\//, ""));
    const file = path.join(dataDir, rel);
    if (!file.startsWith(dataDir + path.sep) || !fs.existsSync(file)) {
      return new Response("not found", { status: 404 });
    }
    return fileResponse(file);
  },
};

const queryVec = storedQueryVector(4321);
const query = "What does DOW-UAP-D017 say about the lights seen near Apollo 17?";

const realParse = JSON.parse;
JSON.parse = function parse(...args) {
  const out = realParse.apply(this, args);
  sample();
  return out;
};
const realDecode = TextDecoder.prototype.decode;
TextDecoder.prototype.decode = function decode(...args) {
  const out = realDecode.apply(this, args);
  sample();
  return out;
};

_resetCaches();
const baseline = live();
peak = baseline;
const timer = setInterval(sample, 1);
const concurrency = Number(process.env.PROBE_CONCURRENCY || 2);
const results = await Promise.all(
  Array.from({ length: concurrency }, () =>
    retrievePassages(query, 20, { ASSETS }, async () => queryVec),
  ),
);
clearInterval(timer);
sample();
JSON.parse = realParse;
TextDecoder.prototype.decode = realDecode;

console.log(
  JSON.stringify({
    baseline,
    peak,
    peakDelta: peak - baseline,
    passages: results[0].length,
    first: results[0][0] && `${results[0][0].card_id}-p${results[0][0].page}`,
  }),
);
