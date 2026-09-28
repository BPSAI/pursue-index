// Serve `/data/<name>` for payloads published as parts.
//
// Cloudflare Workers refuses any static asset over 25 MiB, so an oversize
// payload ships as content-addressed `<name>.part-NNN-<sha12><ext>` files
// plus `<name>.chunks.json`; only the names the manifest lists are read
// (see web/src/lib/chunked-asset.js). Site code loads the parts directly
// through that shared loader; this route keeps the documented public URL
// (`/data/pages-cleaned.json`, `/data/embeddings.bin`, …) answering with
// the reassembled bytes, streamed part by part so the Worker never buffers
// the whole payload.

import { MANIFEST_SUFFIX, manifestUrl, parseManifest } from "../web/src/lib/chunked-asset.js";

const DATA_FILE = /^\/data\/[^/]+$/;

const CONTENT_TYPES = {
  ".json": "application/json; charset=utf-8",
  ".bin": "application/octet-stream",
};

function contentType(name) {
  const ext = name.slice(name.lastIndexOf("."));
  return CONTENT_TYPES[ext] ?? "application/octet-stream";
}

/** Pipe each part's body into `writable` in manifest order. */
async function pipeParts(partUrls, env, writable) {
  try {
    for (const url of partUrls) {
      const res = await env.ASSETS.fetch(url);
      if (!res.ok || !res.body) throw new Error(`${url}: ${res.status}`);
      await res.body.pipeTo(writable, { preventClose: true });
    }
    await writable.close();
  } catch (err) {
    console.error("chunked asset stream failed", err);
    await writable.abort(err).catch(() => {});
  }
}

/**
 * Response for a GET/HEAD of a chunked `/data/<name>`, or null when the
 * request is not one (not under /data, or no manifest) so the caller keeps
 * the original ASSETS response.
 */
export async function serveChunkedAsset(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") return null;
  const url = new URL(request.url);
  if (!DATA_FILE.test(url.pathname) || url.pathname.endsWith(MANIFEST_SUFFIX)) return null;
  const mUrl = manifestUrl(`${url.origin}${url.pathname}`);
  const mres = await env.ASSETS.fetch(mUrl);
  if (!mres.ok) return null;
  const manifest = parseManifest(await mres.json(), url.pathname + MANIFEST_SUFFIX);
  const name = url.pathname.slice("/data/".length);
  const headers = new Headers({
    "Content-Type": contentType(name),
    "Content-Length": String(manifest.size),
  });
  if (manifest.sha256) headers.set("ETag", `"sha256-${manifest.sha256}"`);
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });

  const partUrls = manifest.parts.map((p) => `${url.origin}/data/${p.path}`);
  // FixedLengthStream (Workers runtime) lets the edge send Content-Length.
  const { readable, writable } =
    typeof FixedLengthStream === "function"
      ? new FixedLengthStream(manifest.size)
      : new TransformStream();
  pipeParts(partUrls, env, writable);
  return new Response(readable, { status: 200, headers });
}
