// Self-hosted PDF route handler for GET /pdf/:card_id.pdf.
//
// Why this exists:
//   war.gov / Akamai shipped cross-origin framing protection in May 2026
//   (X-Frame-Options / frame-ancestors). The corpus PDFs still load when
//   opened directly, but iframe embeds from pursueindex.com get blocked
//   and Chrome surfaces them as `chrome-error://chromewebdata/`. We mirror
//   the corpus into Cloudflare R2 (`pursue-pdfs`, binding `PDFS`) and
//   serve the PDFs from this same-origin route instead. The OPEN ↗ link
//   on the card detail page still points at war.gov so it remains the
//   cite-of-record; only the iframe was changed.
//
// Contract pinned by `worker/tests/pdf.test.js`:
//   - card_id must match /^[a-f0-9]{16}$/ (lowercase). Anything else → 400.
//   - missing object → 404 text/plain (GET and HEAD).
//   - 200 with PDF/disposition/cache/etag/length/accept-ranges headers.
//   - HEAD mirrors GET headers but ships an empty body.
//   - Range: bytes=N-M → 206 with Content-Range.
//   - Range: bytes=N-   → 206 with offset only (R2 streams to EOF).
//   - Range past EOF (offset >= size) → 416 with `Content-Range: bytes */<size>`.
//   - Malformed Range (suffix-range, multi-range, garbage) falls back to a
//     full 200 (defense-in-depth — matches nginx/CloudFront behavior).

/** Pinned card_id format: 16 hex chars, lowercase. Mirrors the manifest. */
export const CARD_ID_RE = /^[a-f0-9]{16}$/;

/**
 * Parse a `Range: bytes=N-M` (or `bytes=N-`) header into the
 * `R2GetOptions.range` shape Cloudflare's R2 binding accepts:
 *   { offset, length? }
 *
 * Returns null when the header is absent or malformed; callers fall back
 * to a full GET in that case (matches nginx/most CDNs).
 *
 * Why we don't support multipart ranges: the PDF.js viewer only ever
 * issues single-range requests, and supporting multipart would balloon
 * this handler past its useful complexity budget.
 */
export function parseRangeHeader(header) {
  if (!header) return null;
  // Must start with the bytes unit. Anything else (rows=, items=, garbage)
  // is treated as no range — return null and let the caller serve the full
  // body. This is intentional: 416 on "rows=0-99" surprises real clients.
  const m = /^bytes=(\d+)-(\d*)$/.exec(header.trim());
  if (!m) return null;
  const start = Number(m[1]);
  const endStr = m[2];
  if (!Number.isFinite(start)) return null;
  if (endStr === "") {
    // Open-ended `bytes=N-` — R2 takes offset only and streams to EOF.
    return { offset: start };
  }
  const end = Number(endStr);
  if (!Number.isFinite(end) || end < start) return null;
  return { offset: start, length: end - start + 1 };
}

/**
 * Build the response headers common to both 200 and 206 responses for
 * any R2-served object.
 *
 * Sprint 4g: callers pass an explicit ``cacheControl`` because the
 * cacheability of an R2 object depends entirely on whether the URL is
 * content-addressed:
 *   * /pdf/<card_id>.pdf       — MUTABLE. card_id = sha256(asset_url
 *     || title)[:16], NOT sha256(bytes). Upstream silently re-published
 *     79 cards under their existing card_ids on 2026-05-14 with
 *     different bytes. ``immutable`` was a lie here; we now use a
 *     short max-age + SWR matching the Sprint 2.1 worker-cache pattern
 *     for /data/*.json.
 *   * /archive/<byte_sha256>.<ext> — IMMUTABLE. URL is content-addressed
 *     by sha256 of bytes; if bytes change, sha changes, URL changes.
 *     ``immutable`` is honest.
 */
function buildHeaders({ filename, etag, contentType, cacheControl }) {
  const headers = new Headers();
  headers.set("Content-Type", contentType);
  headers.set("Content-Disposition", `inline; filename="${filename}"`);
  headers.set("Cache-Control", cacheControl);
  headers.set("Accept-Ranges", "bytes");
  if (etag) headers.set("ETag", etag);
  return headers;
}

/** Cache-Control for the mutable current-pointer route /pdf/<card_id>.pdf.
 *
 * Matches the Sprint 2.1 worker policy for /data/*.json (1h fresh, 24h
 * SWR). Critically NO ``immutable`` — bytes at this URL can change
 * upstream-silent at any time.
 */
const MUTABLE_CACHE = "public, max-age=3600, stale-while-revalidate=86400";

/** Cache-Control for the content-addressed /archive/<sha>.<ext> route. */
const IMMUTABLE_CACHE = "public, max-age=31536000, immutable";

/** Allowed extensions for the /archive/ route. Strict allowlist to
 * prevent serving arbitrary R2 keys (e.g., scripts, executables).
 *
 * Currently-mapped formats:
 *   - pdf  application/pdf  (188 today — primary archive type)
 *   - mp4  video/mp4        (28 today — added PR #71 after Codex
 *                            flagged 9 cards with .mp4 archive_keys
 *                            were 400ing in /altered + card banners)
 *   - png  image/png        (8 today)
 *   - jpg  image/jpeg       (6 today)
 *   - jpeg image/jpeg       (0 today — allowlisted for future scrapes
 *                            that report ``.jpeg`` rather than ``.jpg``)
 *   - gif  image/gif        (0 today — allowlisted defensively for
 *                            historical image formats)
 *   - webp image/webp       (0 today — allowlisted for modern image
 *                            scrapes / re-encoded archives)
 *
 * Audit registry distribution via:
 *   jq -r '.archive_key' data/asset-bytes-registry.jsonl \
 *     | grep -oE '\.[a-zA-Z0-9]+$' | sort | uniq -c
 *
 * Single source of truth — the consumer-side regex in
 * web/src/lib/byte-display.ts imports this at build time (via the
 * colocated test) so the two sides can't drift. Nayru PR #79
 * round-6 P1 / round-7 P2 (docstring expansion).
 */
export const ARCHIVE_EXT_TO_CONTENT_TYPE = {
  pdf: "application/pdf",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  mp4: "video/mp4",
};

/** byte_sha256 in canonical lowercase 64-hex form (matches asset-bytes-
 * registry.jsonl). Strict — uppercase, partial, or non-hex inputs
 * reject at the router edge.
 */
export const BYTE_SHA_RE = /^[a-f0-9]{64}$/;

/**
 * Serve a PDF from the R2 binding given a validated card_id.
 *
 * Streams the body directly back via Response — never buffers, so a
 * 50 MB PDF doesn't pin Worker memory. R2's `body` is already a
 * ReadableStream<Uint8Array> in the Workers runtime.
 */
async function serveR2Object(request, env, { key, filename, contentType, cacheControl, notFoundMessage }) {
  const isHead = request.method === "HEAD";
  const range = parseRangeHeader(request.headers.get("Range"));
  const opts = range ? { range } : undefined;
  const obj = await env.PDFS.get(key, opts);
  if (obj == null) {
    return new Response(notFoundMessage, {
      status: 404,
      headers: { "Content-Type": "text/plain" },
    });
  }
  // RFC 9110 §15.5.17: an unsatisfiable range (offset past EOF) MUST return
  // 416 with `Content-Range: bytes */<complete-length>` so clients can
  // recompute. We check this AFTER the R2 round-trip because we need the
  // authoritative size — but we don't re-fetch; obj.size is enough.
  if (range && range.offset >= obj.size) {
    return new Response("range not satisfiable", {
      status: 416,
      headers: {
        "Content-Type": "text/plain",
        "Content-Range": `bytes */${obj.size}`,
      },
    });
  }
  const etag = obj.httpEtag ?? obj.etag;
  const headers = buildHeaders({ filename, etag, contentType, cacheControl });
  // HEAD must report the full set of GET headers (Content-Length, ETag,
  // Accept-Ranges) but ship a null body. The Response constructor accepts
  // `null` as body, which is the spec-compliant way to omit it.
  const body = isHead ? null : obj.body;
  // Determine status + Content-Length + Content-Range based on range presence.
  if (range && obj.range) {
    const offset = obj.range.offset ?? 0;
    const length = obj.range.length ?? Math.max(obj.size - offset, 0);
    const end = offset + length - 1;
    headers.set("Content-Length", String(length));
    headers.set("Content-Range", `bytes ${offset}-${end}/${obj.size}`);
    return new Response(body, { status: 206, headers });
  }
  headers.set("Content-Length", String(obj.size));
  return new Response(body, { status: 200, headers });
}

export async function serveR2Pdf(request, env, cardId) {
  return serveR2Object(request, env, {
    key: `${cardId}.pdf`,
    filename: `${cardId}.pdf`,
    contentType: "application/pdf",
    cacheControl: MUTABLE_CACHE,
    notFoundMessage: "PDF not found",
  });
}

// Sprint 4n followup: video route. Tranche-2 (2026-05-22) shipped 51
// DOD MP4s into the same `PDFS` R2 bucket at key `<card_id>.mp4` (the
// bucket name is historical — it serves all asset types now). Mirrors
// `serveR2Pdf` exactly except for the key extension + content type +
// not-found message. Cache policy matches `/pdf/<id>.pdf` because the
// `<card_id>.mp4` key is the mutable current-pointer (same shape: a
// silent same-URL-different-bytes overlay on a video would land at a
// new `archive/<sha>.mp4` key but the `<card_id>.mp4` pointer rotates
// to the new bytes). Reader-mode video tags + the gallery video lane
// hit this route so they can frame-embed same-origin (war.gov DVIDS
// iframes carry framing protection that blocks cross-origin embed in
// some browsers).
export async function serveR2Video(request, env, cardId) {
  return serveR2Object(request, env, {
    key: `${cardId}.mp4`,
    filename: `${cardId}.mp4`,
    contentType: "video/mp4",
    cacheControl: MUTABLE_CACHE,
    notFoundMessage: "Video not found",
  });
}

/**
 * Serve preserved bytes from R2 key ``archive/<sha>.<ext>``.
 *
 * Sprint 4g. The URL is content-addressed by byte_sha256, so:
 *   * Cache-Control is honestly immutable.
 *   * Path traversal is structurally impossible — the sha must match
 *     ``BYTE_SHA_RE`` (64-hex lowercase) and the extension must be in
 *     the strict allowlist (PDF + common image formats). Anything else
 *     is rejected at the router edge before R2 is consulted.
 */
export async function serveR2Archive(request, env, sha, ext) {
  const contentType = ARCHIVE_EXT_TO_CONTENT_TYPE[ext];
  return serveR2Object(request, env, {
    key: `archive/${sha}.${ext}`,
    filename: `${sha}.${ext}`,
    contentType,
    cacheControl: IMMUTABLE_CACHE,
    notFoundMessage: "Archived object not found",
  });
}

/**
 * Match `GET|HEAD /pdf/:card_id.pdf` and dispatch. Returns null when the
 * request isn't ours so the caller can fall through to other routes.
 *
 * We accept HEAD because CDN warmers and `curl -I` need to size the entity
 * without downloading it; the handler reuses the GET path and replaces the
 * body with null. POST/PUT/etc. still fall through to ASSETS (which 404s
 * in production) rather than 405-ing — keeping the static surface the only
 * thing answering on this path family.
 */
export async function tryHandlePdfRoute(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") return null;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/pdf/")) return null;
  if (!url.pathname.endsWith(".pdf")) return null;
  const cardId = url.pathname.slice("/pdf/".length, -".pdf".length);
  if (!CARD_ID_RE.test(cardId)) {
    return new Response("invalid card_id", {
      status: 400,
      headers: { "Content-Type": "text/plain" },
    });
  }
  return serveR2Pdf(request, env, cardId);
}

/**
 * Match `GET|HEAD /video/:card_id.mp4` and dispatch. Mirrors
 * `tryHandlePdfRoute` shape so the dispatch chain in worker/index.js
 * stays uniform. Returns null when the request isn't ours so the
 * caller can fall through.
 */
export async function tryHandleVideoRoute(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") return null;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/video/")) return null;
  if (!url.pathname.endsWith(".mp4")) return null;
  const cardId = url.pathname.slice("/video/".length, -".mp4".length);
  if (!CARD_ID_RE.test(cardId)) {
    return new Response("invalid card_id", {
      status: 400,
      headers: { "Content-Type": "text/plain" },
    });
  }
  return serveR2Video(request, env, cardId);
}

/**
 * Match ``GET|HEAD /archive/<byte_sha256>.<ext>`` and dispatch to the
 * archived-bytes serve path. Returns null when the request isn't ours
 * so the caller can fall through to other routes.
 *
 * Strict parse-before-serve: both the sha and the extension must
 * validate before the R2 binding is consulted. A path like
 * ``/archive/../etc/passwd`` returns null at the dot check and falls
 * through to static-asset handling (which 404s).
 */
export async function tryHandleArchiveRoute(request, env) {
  if (request.method !== "GET" && request.method !== "HEAD") return null;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/archive/")) return null;
  const trailing = url.pathname.slice("/archive/".length);
  // Require exactly one '.' separator with hex sha on the left + allowed
  // ext on the right. Reject anything else (including missing extension,
  // multiple dots, slashes from path-traversal attempts).
  const dotIdx = trailing.indexOf(".");
  if (dotIdx <= 0 || dotIdx !== trailing.lastIndexOf(".")) return null;
  if (trailing.includes("/")) return null;
  const sha = trailing.slice(0, dotIdx);
  const ext = trailing.slice(dotIdx + 1);
  if (!BYTE_SHA_RE.test(sha)) {
    return new Response("invalid byte_sha256", {
      status: 400,
      headers: { "Content-Type": "text/plain" },
    });
  }
  if (!Object.prototype.hasOwnProperty.call(ARCHIVE_EXT_TO_CONTENT_TYPE, ext)) {
    return new Response("disallowed extension", {
      status: 400,
      headers: { "Content-Type": "text/plain" },
    });
  }
  return serveR2Archive(request, env, sha, ext);
}
