// Float16 scoring: the Worker keeps the shipped vectors as raw float16
// (a Uint16Array, half the bytes of a decoded Float32Array) and scores the
// float32 query against them through a 65,536-entry lookup table and
// precomputed row norms. These tests pin that path to the float32 one it
// replaces: same ids, same order, scores within 1e-3 — on random fixtures
// and on the committed corpus, with stored vectors as queries (no network).

import { describe, test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cosineTopK } from "../retrieve.js";
import {
  cosineTopKF16,
  float16Lut,
  float16ToFloat32,
  loadFloat16Asset,
  rowNorms,
} from "../retrieve_vectors.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.resolve(here, "../../web/public/data");

// Deterministic PRNG so a failure reproduces.
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Round a float to the nearest float16 bit pattern (normal range only,
// which is all an embedding component needs).
function toHalf(f) {
  if (f === 0) return 0;
  const sign = f < 0 ? 0x8000 : 0;
  const a = Math.abs(f);
  let e = Math.floor(Math.log2(a));
  if (e < -14) return sign; // flush tiny values to zero
  let frac = Math.round((a / 2 ** e - 1) * 1024);
  if (frac === 1024) {
    frac = 0;
    e += 1;
  }
  return sign | ((e + 15) << 10) | frac;
}

function assertSameTopK(got, want, label) {
  assert.equal(got.length, want.length, `${label}: length`);
  got.forEach((h, i) => {
    assert.equal(h.index, want[i].index, `${label}: rank ${i} index`);
    assert.ok(Math.abs(h.score - want[i].score) <= 1e-3, `${label}: rank ${i} score ${h.score} vs ${want[i].score}`);
  });
}

describe("float16Lut", () => {
  test("decodes every bit pattern exactly like float16ToFloat32", () => {
    const all = Uint16Array.from({ length: 65536 }, (_, i) => i);
    const want = float16ToFloat32(all.buffer);
    const lut = float16Lut();
    assert.equal(lut.length, 65536);
    assert.deepEqual(new Uint32Array(lut.buffer), new Uint32Array(want.buffer));
    assert.equal(float16Lut(), lut, "built once and reused");
  });
});

describe("cosineTopKF16", () => {
  test("matches the float32 path on random fixtures (ids, order, scores)", () => {
    const rand = rng(7);
    const n = 600;
    const dim = 64;
    const u16 = new Uint16Array(n * dim);
    for (let i = 0; i < u16.length; i += 1) u16[i] = toHalf((rand() - 0.5) * 0.25);
    // A zero row and a duplicate row: the zero-norm guard and tie order.
    u16.fill(0, 5 * dim, 6 * dim);
    u16.copyWithin(9 * dim, 3 * dim, 4 * dim);
    const f32 = float16ToFloat32(u16.buffer);
    const lut = float16Lut();
    const norms = rowNorms(u16, n, dim, lut);
    for (let q = 0; q < 25; q += 1) {
      const query = Float32Array.from({ length: dim }, () => rand() - 0.5);
      if (q === 0) query.set(f32.subarray(3 * dim, 4 * dim)); // ties rows 3 and 9
      for (const k of [1, 8, 20, n + 5]) {
        assertSameTopK(
          cosineTopKF16(query, u16, norms, lut, k, n),
          cosineTopK(query, f32, k, n),
          `query ${q} k=${k}`,
        );
      }
    }
  });

  test("rowNorms are the float32 path's per-row magnitudes", () => {
    const u16 = Uint16Array.from([0x3c00, 0x3c00, 0, 0, 0x4000, 0]);
    const norms = rowNorms(u16, 3, 2, float16Lut());
    assert.deepEqual([...norms], [Math.SQRT2, 0, 2]);
  });
});

describe("loadFloat16Asset", () => {
  const u16 = Uint16Array.from({ length: 64 }, (_, i) => (i * 2654435761) >>> 16);
  const whole = new Uint8Array(u16.buffer.slice(0));

  test("streams parts split mid-value into the exact Uint16Array", async () => {
    const edges = [0, 37, 81, whole.length];
    const parts = edges.slice(0, -1).map((s, i) => [`embeddings.bin.part-00${i}-0123456789ab.bin`, whole.slice(s, edges[i + 1])]);
    const manifest = JSON.stringify({
      name: "embeddings.bin",
      size: whole.length,
      parts: parts.map(([p, b]) => ({ path: p, size: b.length })),
    });
    const fetchFn = async (url) => {
      const name = url.slice(url.lastIndexOf("/") + 1);
      if (name === "embeddings.bin.chunks.json") return new Response(manifest);
      const bytes = parts.find(([p]) => p === name)[1];
      let at = 0;
      const body = new ReadableStream({
        pull(c) {
          if (at >= bytes.length) return c.close();
          c.enqueue(bytes.slice(at, at + 3)); // 3-byte chunks straddle every value
          at += 3;
        },
      });
      return new Response(body);
    };
    const out = await loadFloat16Asset("https://assets/data/embeddings.bin", fetchFn, u16.length);
    assert.ok(out instanceof Uint16Array);
    assert.deepEqual([...out], [...u16]);
  });

  test("rejects a payload whose size disagrees with the index; null on 404", async () => {
    const fetchFn = async (url) =>
      url.endsWith(".chunks.json") ? new Response("nf", { status: 404 }) : new Response(whole);
    for (const count of [u16.length + 1, u16.length - 1]) {
      await assert.rejects(loadFloat16Asset("https://assets/data/embeddings.bin", fetchFn, count), /embeddings\.bin/);
    }
    const missing = async () => new Response("nf", { status: 404 });
    assert.equal(await loadFloat16Asset("https://assets/data/embeddings.bin", missing, 4), null);
  });
});

describe("committed corpus", () => {
  test("float16 top-20 matches float32 top-20 for stored query vectors", () => {
    const index = JSON.parse(fs.readFileSync(path.join(DATA, "embed_index.json"), "utf8"));
    const manifest = JSON.parse(fs.readFileSync(path.join(DATA, "embeddings.bin.chunks.json"), "utf8"));
    const bytes = Buffer.concat(manifest.parts.map((p) => fs.readFileSync(path.join(DATA, p.path))));
    const { n, dim } = index;
    assert.equal(bytes.length, n * dim * 2);
    const u16 = new Uint16Array(bytes.buffer, bytes.byteOffset, n * dim);
    const f32 = float16ToFloat32(u16.slice().buffer);
    const lut = float16Lut();
    const norms = rowNorms(u16, n, dim, lut);
    const rand = rng(11);
    for (const row of [0, 1234, 4321, 9000, n - 1]) {
      // A stored row, nudged so it is a query near that row rather than the row itself.
      const query = Float32Array.from(f32.subarray(row * dim, (row + 1) * dim), (v) => v + (rand() - 0.5) * 0.02);
      const want = cosineTopK(query, f32, 20, n);
      assertSameTopK(cosineTopKF16(query, u16, norms, lut, 20, n), want, `row ${row}`);
      assert.equal(want[0].index, row, "the nudged row is still its own nearest neighbour");
    }
  });
});
