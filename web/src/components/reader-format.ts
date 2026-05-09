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
 * Build a deep-link to a specific page in the source PDF using the
 * standard PDF.js fragment syntax (`#page=N`). Returns null when the
 * input URL is empty so the caller can hide the link gracefully.
 */
export function pdfPageHref(assetUrl: string | null | undefined, page: number): string | null {
  if (!assetUrl) return null;
  if (!Number.isInteger(page) || page < 1) return null;
  // Strip any pre-existing fragment so we don't end up with two.
  const base = assetUrl.split("#")[0];
  return `${base}#page=${page}`;
}

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
