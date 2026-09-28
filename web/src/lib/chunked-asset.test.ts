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
    ["pages-cleaned.json.part-000.json", a],
    ["pages-cleaned.json.part-001.json", b],
    ["pages-cleaned.json.part-002.json", c],
  ]);
  const { fn } = fakeFetch({
    "https://assets/data/pages-cleaned.json.chunks.json": JSON.stringify(m),
    "https://assets/data/pages-cleaned.json.part-000.json": a,
    "https://assets/data/pages-cleaned.json.part-001.json": b,
    "https://assets/data/pages-cleaned.json.part-002.json": c,
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
  const m = manifestFor("x.bin", [["x.bin.part-000.bin", a], ["x.bin.part-001.bin", a]]);
  const missing = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(m),
    "/data/x.bin.part-000.bin": a,
  });
  await assert.rejects(loadAssetBytes("/data/x.bin", missing.fn), /x\.bin\.part-001\.bin/);
  const short = fakeFetch({
    "/data/x.bin.chunks.json": JSON.stringify(m),
    "/data/x.bin.part-000.bin": a,
    "/data/x.bin.part-001.bin": new Uint8Array([1]),
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
  writeFileSync(join(dir, "c.json.part-000.json"), a);
  writeFileSync(join(dir, "c.json.part-001.json"), b);
  writeFileSync(
    join(dir, "c.json.chunks.json"),
    JSON.stringify(manifestFor("c.json", [["c.json.part-000.json", a], ["c.json.part-001.json", b]])),
  );
  assert.deepEqual(readAssetJsonSync(join(dir, "c.json"), fs), { pages: [1, 2] });
  assert.equal(assetExistsSync(join(dir, "c.json"), fs), true);

  writeFileSync(join(dir, "plain.json"), "[7]");
  assert.deepEqual(readAssetJsonSync(join(dir, "plain.json"), fs), [7]);

  assert.equal(readAssetSync(join(dir, "absent.json"), fs), null);
  assert.equal(assetExistsSync(join(dir, "absent.json"), fs), false);
});
