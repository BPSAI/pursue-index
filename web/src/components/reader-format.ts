/**
 * Pure helpers for the reader-mode OCR view.
 *
 * Reformat text into paragraphs without paraphrasing. The OCR transcript
 * stays byte-identical to what the engine produced — this layer only
 * re-flows whitespace so prose typography reads naturally.
 *
 * Rules:
 *   - 2+ consecutive newlines  → paragraph break
 *   - Single newline within a paragraph → soft break, joined with a space
 *   - Trim each paragraph; drop fully-empty ones
 *
 * No LLM cleanup, no spelling fixes, no paraphrasing.
 */
export function reformatOcrText(raw: string): string[] {
  if (!raw) return [];
  // Normalize line endings then split on runs of 2+ newlines (allowing
  // whitespace between them — OCR sometimes leaves stray spaces on blank lines).
  const blocks = raw
    .replace(/\r\n?/g, "\n")
    .split(/\n[ \t]*\n+/);
  const paragraphs: string[] = [];
  for (const block of blocks) {
    // Within a paragraph, single newlines come from line wrap, not intent —
    // join with a space so the prose flows. Collapse double-spaces.
    const joined = block
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .join(" ")
      .replace(/[ \t]{2,}/g, " ")
      .trim();
    if (joined) paragraphs.push(joined);
  }
  return paragraphs;
}

/** Parse `#page-N` from a URL hash. Returns null when absent or malformed. */
export function readPageFromHash(hash: string | null | undefined): number | null {
  if (!hash) return null;
  const m = hash.match(/^#?page-(\d+)$/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/**
 * Parse `?page=N` from a URL query string. Returns null when absent or
 * malformed. Forward-compat hook: nothing in the corpus currently emits
 * `?page=N`, but external citation sources (or future Trello cards) might,
 * so the reader normalizes both forms onto the same active-page state.
 *
 * No try/catch: `URLSearchParams` does not throw on malformed input —
 * it silently yields no value for missing keys. (Verified in
 * reader-format.test.ts via `?%ZZ` and duplicate-key cases.)
 */
export function readPageFromQuery(search: string | null | undefined): number | null {
  if (!search) return null;
  // URLSearchParams tolerates with-or-without leading `?`.
  const normalized = search.startsWith("?") ? search : `?${search}`;
  const value = new URLSearchParams(normalized).get("page");
  if (!value) return null;
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/**
 * Drop the `?page=N` parameter from a query string, preserving any other
 * params and the leading `?` only when something remains. Returns "" for
 * empty/null input. Used by the page-load bootstrap to canonicalize URLs
 * after promoting `?page=N` → `#page-N`, so a copy-paste yields the
 * cleaner `/card/<id>#page-N` form rather than `/card/<id>?page=5#page-5`.
 */
export function stripPageParam(search: string | null | undefined): string {
  if (!search) return "";
  const normalized = search.startsWith("?") ? search.slice(1) : search;
  if (!normalized) return "";
  const params = new URLSearchParams(normalized);
  params.delete("page");
  const out = params.toString();
  return out ? `?${out}` : "";
}

/**
 * Compute the canonical card URL after `?page=N` normalization. Returns
 * the new `/card/<id>[?qs][#hash]` string when a rewrite is warranted,
 * or null when the URL is already canonical and the bootstrap can skip
 * `replaceState`.
 *
 * Cases:
 *   - `?page=N` only            → promote to `#page-N`, drop the query.
 *   - `?page=N` + `#page-N`     → drop only the redundant query.
 *   - `?page=N` + `#other`      → drop the query, keep the hash.
 *   - no `?page=N`              → null (no-op).
 *
 * Pure: takes pathname/search/hash strings and returns a string. Lives
 * here so it can be unit-tested without `window.location`/`history`.
 */
export function promotedCardUrl(
  pathname: string,
  search: string | null | undefined,
  hash: string | null | undefined,
): string | null {
  const fromQuery = readPageFromQuery(search);
  if (fromQuery == null) return null;
  const cleanedSearch = stripPageParam(search);
  const existingHash = hash ?? "";
  if (existingHash) {
    return `${pathname}${cleanedSearch}${existingHash}`;
  }
  return `${pathname}${cleanedSearch}#page-${fromQuery}`;
}

/**
 * Resolve the active page number from a URL's hash and query parts.
 * Hash wins when both are present so reader-mode deep-links stay
 * deterministic when a user copies a URL the reader itself produced.
 */
export function readPageFromLocation(
  hash: string | null | undefined,
  search: string | null | undefined,
): number | null {
  const fromHash = readPageFromHash(hash);
  if (fromHash != null) return fromHash;
  return readPageFromQuery(search);
}

/**
 * Build a deep-link to a specific page in the source PDF using the
 * standard PDF.js fragment syntax (`#page=N`). Returns null when the
 * input URL is empty so the caller can hide the link gracefully.
 *
 * Preserves non-`page=` fragment params (zoom, view, ...) so the citation
 * "Read on war.gov" link survives a user-set zoom level. Only the `page=`
 * key is rewritten.
 */
export function pdfPageHref(assetUrl: string | null | undefined, page: number): string | null {
  if (!assetUrl) return null;
  if (!Number.isInteger(page) || page < 1) return null;
  const hashIdx = assetUrl.indexOf("#");
  const base = hashIdx === -1 ? assetUrl : assetUrl.slice(0, hashIdx);
  const fragment = hashIdx === -1 ? "" : assetUrl.slice(hashIdx + 1);
  if (!fragment) return `${base}#page=${page}`;
  // Hand-parse — same lenient PDF.js fragment grammar as nextIframeSrc.
  const parts = fragment.split("&").filter((p) => p.length > 0 && !p.startsWith("page="));
  parts.unshift(`page=${page}`);
  return `${base}#${parts.join("&")}`;
}

// `buildPdfIframeSrc` was removed: it had no runtime consumer (vaivora P2 #13).
// `nextIframeSrc` in pdf-iframe-sync.ts is the single source of truth for
// PDF iframe URL construction.

/**
 * Clamp a candidate page number into the valid 1..total range. Used by
 * the reader-mode prev/next controls and the on-mount hash router.
 * Falls back to 1 for non-finite or non-positive inputs so we never
 * leave the UI on a "page 0 of 5" state.
 */
export function clampPageIndex(candidate: number | null | undefined, total: number): number {
  if (typeof candidate !== "number" || !Number.isFinite(candidate)) return 1;
  if (candidate < 1) return 1;
  if (total < 1) return 1;
  if (candidate > total) return total;
  return Math.floor(candidate);
}

export type ReaderMode = "raw" | "reader";

/** localStorage key for the user's mode preference (sticky across cards). */
export const READER_MODE_KEY = "pursueindex.reader.mode";

/**
 * Load the persisted reader-mode preference. Defaults to "raw" — the
 * existing OCR display — so first-time visitors and existing users see
 * the canonical transcript view they expect. Garbage values fall back
 * to "raw" rather than throwing, since this read happens during render.
 */
export function loadReaderMode(storage: Storage | null | undefined): ReaderMode {
  if (!storage) return "raw";
  try {
    const v = storage.getItem(READER_MODE_KEY);
    return v === "reader" || v === "raw" ? v : "raw";
  } catch {
    // localStorage can throw in private-browsing modes.
    return "raw";
  }
}

/** Persist the reader-mode preference. Silently no-ops when storage is
 *  unavailable (SSR, private browsing, disabled storage). */
export function saveReaderMode(storage: Storage | null | undefined, mode: ReaderMode): void {
  if (!storage) return;
  try {
    storage.setItem(READER_MODE_KEY, mode);
  } catch {
    /* private-browsing / quota — best-effort persistence */
  }
}
