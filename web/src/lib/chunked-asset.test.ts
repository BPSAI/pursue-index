/**
 * The one loader every consumer of a `web/public/data` payload goes through.
 *
 * A payload over the 24 MiB deploy budget ships as ordered parts plus a
 * `<name>.chunks.json` manifest (written by
 * `pursue_index.release.chunked_asset`). These tests pin the reassembly
 * contract for both the fetch path (browser + Worker) and the fs path
 * (Astro build-time readers).
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  loadAssetBytes,
  loadAssetJson,
  manifestUrl,
  readAssetSync,
  readAssetJsonSync,
  assetExistsSync,
} from "./chunked-asset.js";

const enc = new TextEncoder();

function manifestFor(name: string, parts: Array<[string, Uint8Array]>) {
  return {
    schema: "pursue-chunked-asset/1",
    name,
    size: parts.reduce((n, [, b]) => n + b.length, 0),
    sha256: "unchecked-in-js",
    parts: parts.map(([path, b]) => ({ path, size: b.length })),
  };
}

function fakeFetch(files: Record<string, Uint8Array | string>) {
  const seen: string[] = [];
  const fn = async (url: string) => {
    seen.push(url);
    const body = files[url];
    if (body === undefined) return new Response("not found", { status: 404 });
    return new Response(typeof body === "string" ? body : body, { status: 200 });
  };
  return { fn, seen };
}

test("manifestUrl appends the manifest suffix", () => {
  assert.equal(manifestUrl("/data/pages.json"), "/data/pages.json.chunks.json");
});

test("reassembles a chunked asset from its parts, in manifest order", async () => {
  const text = JSON.stringify({ pages: [{ text: "é✓".repeat(30) }] });
  const bytes = enc.encode(text);
  // Split mid multi-byte character on purpose: decoding must follow concat.
  const a = bytes.slice(0, 7);
  const b = bytes.slice(7, 50);
  const c = bytes.slice(50);
  const m = manifestFor("pages-cleaned.json", [
    ["pages-cleaned.json.part-000-0123456789ab.json", a],
    ["pages-cleaned.json.part-001-0123456789ab.json", b],
    ["pages-cleaned.json.part-002-0123456789ab.json", c],
  ]);
  const { fn } = fakeFetch({
    "https://assets/data/pages-cleaned.json.chunks.json": JSON.stringify(m),
    "https://assets/data/pages-cleaned.json.part-000-0123456789ab.json": a,
    "https://assets/data/pages-cleaned.json.part-001-0123456789ab.json": b,
    "https://assets/data/pages-cleaned.json.part-002-0123456789ab.json": c,
  });
  const out = await loadAssetJson("https://assets/data/pages-cleaned.json", fn);
  assert.deepEqual(out, JSON.parse(text));
});

test("single-part manifest points at the whole file under its own URL", async () => {
  const body = enc.encode("[1,2,3]");
  const { fn, seen } = fakeFetch({
    "/data/pages.json.chunks.json": JSON.stringify(manifestFor("pages.json", [["pages.json", body]])),
    "/data/pages.json": body,
  });
  assert.deepEqual(await loadAssetJson("/data/pages.json", fn), [1, 2, 3]);
  assert.deepEqual(seen, ["/data/pages.json.chunks.json", "/data/pages.json"]);
});

test("falls back to the plain URL when there is no manifest", async () => {
  const { fn } = fakeFetch({ "/data/x.bin": new Uint8Array([1, 2, 3]) });
  const bytes = await loadAssetBytes("/data/x.bin", fn);
  assert.deepEqual(Array.from(bytes!), [1, 2, 3]);
});

test("returns null when neither manifest nor file exists", async () => {
  const { fn } = fakeFetch({});
  assert.equal(await loadAssetBytes("/data/x.bin", fn), null);
  assert.equal(await loadAssetJson("/data/x.json", fn), null);
});

test("throws when a part is missing or the wrong size", async () => {
  const a = new Uint8Array([1, 2]);
  const m = manifestFor("x.bin", [["x.bin.part-000-0123456789ab.bin", a], ["x.bin.part-001-0123456789ab.bin", a]]);
  const missing = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(m),
    "/data/x.bin.part-000-0123456789ab.bin": a,
  });
  await assert.rejects(loadAssetBytes("/data/x.bin", missing.fn), /x\.bin\.part-001-0123456789ab\.bin/);
  const short = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(m),
    "/data/x.bin.part-000-0123456789ab.bin": a,
    "/data/x.bin.part-001-0123456789ab.bin": new Uint8Array([1]),
  });
  await assert.rejects(loadAssetBytes("/data/x.bin", short.fn), /size/);
});

test("throws on a non-404 error rather than reporting the asset missing", async () => {
  const fn = async () => new Response("boom", { status: 500 });
  await assert.rejects(loadAssetBytes("/data/x.bin", fn), /500/);
});

test("rejects part paths that escape the asset directory", async () => {
  const m = manifestFor("x.bin", [["../secret.bin", new Uint8Array([1])]]);
  const { fn } = fakeFetch({ "/data/x.bin.chunks.json": JSON.stringify(m) });
  await assert.rejects(loadAssetBytes("/data/x.bin", fn), /part path/);
});

test("readAssetSync reassembles parts from disk and falls back to the plain file", () => {
  const dir = mkdtempSync(join(tmpdir(), "chunked-"));
  const fs = { existsSync, readFileSync };
  const a = enc.encode('{"pages":[');
  const b = enc.encode("1,2]}");
  writeFileSync(join(dir, "c.json.part-000-0123456789ab.json"), a);
  writeFileSync(join(dir, "c.json.part-001-0123456789ab.json"), b);
  writeFileSync(
    join(dir, "c.json.chunks.json"),
    JSON.stringify(manifestFor("c.json", [["c.json.part-000-0123456789ab.json", a], ["c.json.part-001-0123456789ab.json", b]])),
  );
  assert.deepEqual(readAssetJsonSync(join(dir, "c.json"), fs), { pages: [1, 2] });
  assert.equal(assetExistsSync(join(dir, "c.json"), fs), true);

  writeFileSync(join(dir, "plain.json"), "[7]");
  assert.deepEqual(readAssetJsonSync(join(dir, "plain.json"), fs), [7]);

  assert.equal(readAssetSync(join(dir, "absent.json"), fs), null);
  assert.equal(assetExistsSync(join(dir, "absent.json"), fs), false);
});

// --- streaming (forEachAssetChunk) --------------------------------------

import { forEachAssetChunk } from "./chunked-asset.js";

/** A Response-like part whose whole-body readers throw: callers must stream. */
function streamingPart(bytes: Uint8Array, chunk: number, log: string[], name: string) {
  let at = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (at >= bytes.length) {
        log.push(`end ${name}`);
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(at, at + chunk));
      at += chunk;
    },
  });
  const refuse = () => {
    throw new Error(`whole-body read of ${name}`);
  };
  return { ok: true, status: 200, body, arrayBuffer: refuse, json: refuse, text: refuse, bytes: refuse };
}

test("forEachAssetChunk streams parts in order, one at a time, never buffering a part", async () => {
  const whole = Uint8Array.from({ length: 23 }, (_, i) => (i * 37) & 0xff);
  const parts: Array<[string, Uint8Array]> = [
    ["x.bin.part-000-0123456789ab.bin", whole.slice(0, 9)],
    ["x.bin.part-001-0123456789ab.bin", whole.slice(9, 18)],
    ["x.bin.part-002-0123456789ab.bin", whole.slice(18)],
  ];
  const log: string[] = [];
  const fn = async (url: string) => {
    const name = url.slice(url.lastIndexOf("/") + 1);
    log.push(`fetch ${name}`);
    if (name === "x.bin.chunks.json") return new Response(JSON.stringify(manifestFor("x.bin", parts)));
    const part = parts.find(([p]) => p === name)!;
    return streamingPart(part[1], 4, log, name) as unknown as Response;
  };
  const seen: number[] = [];
  const res = await forEachAssetChunk("/data/x.bin", fn, (c: Uint8Array) => {
    assert.ok(c.length <= 4);
    seen.push(...c);
  });
  assert.deepEqual(res, { size: 23 });
  assert.deepEqual(seen, Array.from(whole));
  assert.deepEqual(log, [
    "fetch x.bin.chunks.json",
    "fetch x.bin.part-000-0123456789ab.bin", "end x.bin.part-000-0123456789ab.bin",
    "fetch x.bin.part-001-0123456789ab.bin", "end x.bin.part-001-0123456789ab.bin",
    "fetch x.bin.part-002-0123456789ab.bin", "end x.bin.part-002-0123456789ab.bin",
  ]);
});

test("forEachAssetChunk rejects a part whose streamed size differs from the manifest", async () => {
  const a = new Uint8Array([1, 2, 3]);
  const m = manifestFor("x.bin", [["x.bin", a]]);
  const fn = async (url: string) =>
    url.endsWith(".chunks.json")
      ? new Response(JSON.stringify(m))
      : new Response(new Uint8Array([1, 2, 3, 4]));
  await assert.rejects(forEachAssetChunk("/data/x.bin", fn, () => {}), /size/);
});

test("forEachAssetChunk verifies the manifest sha256 with a streaming digest", async () => {
  const { createHash } = await import("node:crypto");
  const nodeDigest = () => {
    const h = createHash("sha256");
    return { update: (c: Uint8Array) => void h.update(c), digestHex: async () => h.digest("hex") };
  };
  const body = new Uint8Array([5, 6, 7, 8]);
  const good = { ...manifestFor("x.bin", [["x.bin", body]]), sha256: createHash("sha256").update(body).digest("hex") };
  const bad = { ...good, sha256: "0".repeat(64) };
  const serve = (m: object) => async (url: string) =>
    url.endsWith(".chunks.json") ? new Response(JSON.stringify(m)) : new Response(body);
  assert.deepEqual(
    await forEachAssetChunk("/data/x.bin", serve(good), () => {}, { createDigest: nodeDigest }),
    { size: 4 },
  );
  await assert.rejects(
    forEachAssetChunk("/data/x.bin", serve(bad), () => {}, { createDigest: nodeDigest }),
    /sha256/,
  );
});

test("forEachAssetChunk streams a plain file without a manifest, and reports a miss as null", async () => {
  const fn = async (url: string) =>
    url === "/data/x.bin" ? new Response(new Uint8Array([9, 9])) : new Response("nf", { status: 404 });
  const got: number[] = [];
  assert.deepEqual(await forEachAssetChunk("/data/x.bin", fn, (c: Uint8Array) => got.push(...c)), { size: 2 });
  assert.deepEqual(got, [9, 9]);
  assert.equal(await forEachAssetChunk("/data/y.bin", fn, () => {}), null);
});

test("a single-part asset is returned without a reassembly copy", async () => {
  const body = new Uint8Array([1, 2, 3]);
  const m = manifestFor("p.json", [["p.json", body]]);
  let partBytes: Uint8Array | null = null;
  const fn = async (url: string) => {
    if (url.endsWith(".chunks.json")) return new Response(JSON.stringify(m));
    const res = new Response(body);
    const buf = new Uint8Array(await res.arrayBuffer());
    partBytes = buf;
    return { ok: true, status: 200, arrayBuffer: async () => buf.buffer } as unknown as Response;
  };
  const out = await loadAssetBytes("/data/p.json", fn);
  assert.equal(out!.buffer, partBytes!.buffer);
});

// --- content-addressed part names ---------------------------------------

test("a stale manifest paired with another release's parts fails loudly", async () => {
  // Release A's manifest (e.g. from a cache) names A's parts; the origin now
  // serves release B, whose parts have different content-addressed names.
  const a0 = new Uint8Array([1, 1]);
  const a1 = new Uint8Array([2, 2]);
  const stale = manifestFor("x.bin", [
    ["x.bin.part-000-aaaaaaaaaaaa.bin", a0],
    ["x.bin.part-001-aaaaaaaaaaab.bin", a1],
  ]);
  const { fn } = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(stale),
    "/data/x.bin.part-000-bbbbbbbbbbbb.bin": new Uint8Array([3, 3]),
    "/data/x.bin.part-001-bbbbbbbbbbbc.bin": new Uint8Array([4, 4]),
  });
  await assert.rejects(loadAssetBytes("/data/x.bin", fn), /x\.bin\.part-000-aaaaaaaaaaaa\.bin: 404/);
  await assert.rejects(forEachAssetChunk("/data/x.bin", fn, () => {}), /404/);
});

test("manifest part names must be the content-addressed name for their index", async () => {
  const b = new Uint8Array([1]);
  const cases: Array<[string, Array<[string, Uint8Array]>]> = [
    ["legacy un-addressed names", [["x.bin.part-000.bin", b], ["x.bin.part-001.bin", b]]],
    ["out of order", [["x.bin.part-001-0123456789ab.bin", b], ["x.bin.part-000-0123456789ab.bin", b]]],
    ["another asset's part", [["y.bin.part-000-0123456789ab.bin", b], ["x.bin.part-001-0123456789ab.bin", b]]],
    ["single part not the asset itself", [["x.bin.part-000-0123456789ab.bin", b]]],
  ];
  for (const [why, parts] of cases) {
    const { fn } = fakeFetch({ "/data/x.bin.chunks.json": JSON.stringify(manifestFor("x.bin", parts)) });
    await assert.rejects(loadAssetBytes("/data/x.bin", fn), /part name/, why);
  }
});

test("a manifest for a different asset is rejected", async () => {
  const body = new Uint8Array([1]);
  const { fn } = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(manifestFor("y.bin", [["y.bin", body]])),
    "/data/y.bin": body,
  });
  await assert.rejects(loadAssetBytes("/data/x.bin", fn), /manifest names y\.bin/);
});
