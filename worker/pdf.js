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
//   - missing object → 404 text/plain.
//   - 200 with PDF/disposition/cache/etag/length/accept-ranges headers.
//   - Range: bytes=N-M → 206 with Content-Range.
//   - Range: bytes=N-   → 206 with offset only (R2 streams to EOF).
//   - Malformed Range falls back to a full 200 (defense-in-depth).

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
 * Build the response headers common to both 200 and 206 responses.
 * Cache-Control is `immutable` because the URL is content-addressed:
 * a card's PDF bytes are pinned to its card_id; if the bytes ever
 * change, the card_id changes (sha256 of asset_url || title).
 */
function baseHeaders(cardId, etag) {
  const headers = new Headers();
  headers.set("Content-Type", "application/pdf");
  headers.set("Content-Disposition", `inline; filename="${cardId}.pdf"`);
  headers.set("Cache-Control", "public, max-age=31536000, immutable");
  headers.set("Accept-Ranges", "bytes");
  if (etag) headers.set("ETag", etag);
  return headers;
}

/**
 * Serve a PDF from the R2 binding given a validated card_id.
 *
 * Streams the body directly back via Response — never buffers, so a
 * 50 MB PDF doesn't pin Worker memory. R2's `body` is already a
 * ReadableStream<Uint8Array> in the Workers runtime.
 */
export async function serveR2Pdf(request, env, cardId) {
  const range = parseRangeHeader(request.headers.get("Range"));
  const opts = range ? { range } : undefined;
  const obj = await env.PDFS.get(`${cardId}.pdf`, opts);
  if (obj == null) {
    return new Response("PDF not found", {
      status: 404,
      headers: { "Content-Type": "text/plain" },
    });
  }
  const etag = obj.httpEtag ?? obj.etag;
  const headers = baseHeaders(cardId, etag);
  // Determine status + Content-Length + Content-Range based on range presence.
  if (range && obj.range) {
    const offset = obj.range.offset ?? 0;
    const length = obj.range.length ?? Math.max(obj.size - offset, 0);
    const end = offset + length - 1;
    headers.set("Content-Length", String(length));
    headers.set("Content-Range", `bytes ${offset}-${end}/${obj.size}`);
    return new Response(obj.body, { status: 206, headers });
  }
  headers.set("Content-Length", String(obj.size));
  return new Response(obj.body, { status: 200, headers });
}

/**
 * Match `GET /pdf/:card_id.pdf` and dispatch. Returns null when the
 * request isn't ours so the caller can fall through to other routes.
 *
 * We deliberately scope this to GET only — POST/PUT/etc. fall through
 * to ASSETS (which 404s in production) rather than 405-ing. The static
 * surface should be the only thing answering on this path family.
 */
export async function tryHandlePdfRoute(request, env) {
  if (request.method !== "GET") return null;
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
