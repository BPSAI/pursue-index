#!/usr/bin/env node
/**
 * Build `web/public/llms.txt` (index) and `web/public/llms-full.txt`
 * (concatenated corpus) — the Jeremy Howard llms.txt convention.
 *
 * The pair gives LLMs two reading modes:
 *
 *   - `/llms.txt`        — short index of canonical URLs + 1-line
 *                          summaries. The "table of contents" model.
 *   - `/llms-full.txt`   — full corpus body, anchor-stable H2
 *                          structure for chunker predictability.
 *
 * Inputs:
 *   - `data/manifests/latest.json`             — card index
 *   - `web/public/data/pages.json` (optional)  — OCR page text
 *   - `web/src/content/finds/*.{md,mdx}`       — reading guides
 *   - `web/src/pages/{methodology,about,cite,support}.astro` — meta pages
 *
 * Output sections in llms-full.txt:
 *
 *   ## Project overview                   (factual blurb)
 *   ## Methodology                        (lifted from /methodology lede)
 *   ## About                              (lifted from /about lede)
 *   ## How to cite                        (lifted from /cite lede)
 *   ## Cards                              (H3 per card)
 *     ### <card_id> — <title>
 *     <agency>, <date>
 *     <canonical url>
 *     <war.gov url>
 *     <first ~500 chars of OCR page 1>
 *   ## Finds                              (H3 per /finds entry)
 *     ### <slug> — <title>
 *     <canonical url>
 *     <frontmatter summary>
 *     <verbatim body excerpt>
 *
 * Run: `node web/scripts/build_llms_txt.mjs`
 * Or as a prebuild hook via package.json.
 */

import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const WEB = resolve(HERE, "..");
const SITE_ORIGIN = "https://pursueindex.com";

const MANIFEST_PATH = resolve(REPO, "data/manifests/latest.json");
const PAGES_PATH = resolve(WEB, "public/data/pages.json");
const FINDS_DIR = resolve(WEB, "src/content/finds");

const OUT_INDEX = resolve(WEB, "public/llms.txt");
const OUT_FULL = resolve(WEB, "public/llms-full.txt");

/** Read JSON from disk, return parsed value or fallback. */
function readJson(path, fallback) {
  try {
    if (!existsSync(path)) return fallback;
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return fallback;
  }
}

/** Build a lookup of first-page OCR text by card_id. */
function buildPageTextLookup() {
  const pages = readJson(PAGES_PATH, []);
  if (!Array.isArray(pages)) return new Map();
  const byCard = new Map();
  for (const row of pages) {
    if (!row || typeof row.text !== "string" || !row.card_id) continue;
    const existing = byCard.get(row.card_id);
    if (existing === undefined || row.page === 1) {
      byCard.set(row.card_id, row.text);
    }
  }
  return byCard;
}

/** Strip MDX-only constructs to keep the body readable as plain text. */
function stripMdx(body) {
  // Remove import lines.
  let out = body.replace(/^import\s.*$/gm, "");
  // Replace <Cite ...> with a textual marker preserving the cite ref.
  out = out.replace(
    /<Cite\s+card=["']([^"']+)["']\s+page=\{?(\d+)\}?(?:\s+q=["']([^"']*)["'])?\s*\/>/g,
    (_m, id, page, q) => `[cite: card ${id} p.${page}${q ? ` "${q}"` : ""}]`,
  );
  // Drop any remaining JSX components (best-effort).
  out = out.replace(/<[A-Z][A-Za-z]*\s[^>]*\/>/g, "");
  out = out.replace(/<\/?[A-Z][A-Za-z]*[^>]*>/g, "");
  return out.trim();
}

/** Parse a `---`-delimited YAML frontmatter block. Minimal parser. */
function parseFrontmatter(raw) {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!m) return { meta: {}, body: raw };
  const yaml = m[1];
  const body = m[2];
  const meta = {};
  let currentKey = null;
  for (const line of yaml.split(/\r?\n/)) {
    if (!line.trim()) continue;
    if (/^[a-zA-Z_]+:/.test(line)) {
      const [k, ...rest] = line.split(":");
      const v = rest.join(":").trim();
      currentKey = k.trim();
      if (v === "" || v === "[]") {
        meta[currentKey] = v === "[]" ? [] : null;
      } else if (v.startsWith("[") && v.endsWith("]")) {
        meta[currentKey] = v
          .slice(1, -1)
          .split(",")
          .map((s) => s.trim().replace(/^["']|["']$/g, ""))
          .filter(Boolean);
      } else {
        meta[currentKey] = v.replace(/^["']|["']$/g, "");
      }
    } else if (/^\s+-\s+/.test(line) && currentKey) {
      // List continuation.
      const v = line.replace(/^\s+-\s+/, "").trim().replace(/^["']|["']$/g, "");
      if (!Array.isArray(meta[currentKey])) meta[currentKey] = [];
      meta[currentKey].push(v);
    }
  }
  return { meta, body };
}

/** Render the llms.txt index — H2 sections, link list per section. */
function renderIndex(cards, finds) {
  const lines = [];
  lines.push("# pursue-index");
  lines.push("");
  lines.push(
    "> Citable archive of the U.S. Department of War PURSUE UAP document releases.",
  );
  lines.push(
    "> Primary-source documents, OCR transcripts, page-level citations.",
  );
  lines.push(`> Source: ${SITE_ORIGIN}`);
  lines.push("");
  lines.push("## Meta");
  lines.push("");
  lines.push(`- [Methodology](${SITE_ORIGIN}/methodology): How the corpus is fetched, hashed, OCR'd, and made reproducible.`);
  lines.push(`- [About](${SITE_ORIGIN}/about): What pursue-index is, and what it is not.`);
  lines.push(`- [How to cite](${SITE_ORIGIN}/cite): Citation patterns for the corpus, individual cards, and OCR transcripts.`);
  lines.push(`- [Support](${SITE_ORIGIN}/support): Operator contact + funding posture.`);
  lines.push(`- [API](${SITE_ORIGIN}/api): Machine-readable endpoints (manifest, pages, embeddings).`);
  lines.push(`- [Removed](${SITE_ORIGIN}/removed): Cards dropped entirely from the upstream manifest; bytes preserved here.`);
  lines.push(`- [Altered](${SITE_ORIGIN}/altered): Cards where upstream re-published bytes under the same identifier; pre-edit version preserved + per-card OCR text diff.`);
  lines.push("");
  lines.push("## Cards");
  lines.push("");
  for (const card of cards) {
    const date = card.incident_date || card.release_date || "";
    const dateLabel = date ? ` (${date})` : "";
    lines.push(
      `- [${card.card_id} — ${card.title}](${SITE_ORIGIN}/card/${card.card_id}): ${card.agency}${dateLabel}.`,
    );
  }
  lines.push("");
  if (finds.length > 0) {
    lines.push("## Finds");
    lines.push("");
    for (const f of finds) {
      const summary = (f.meta.summary || "").replace(/\s+/g, " ").trim();
      const shortSummary = summary.length > 160 ? summary.slice(0, 157) + "…" : summary;
      lines.push(
        `- [${f.slug} — ${f.meta.title}](${SITE_ORIGIN}/finds/${f.slug}): ${shortSummary}`,
      );
    }
    lines.push("");
  }
  return lines.join("\n");
}

/** Render the llms-full.txt corpus body with anchor-stable H2 structure. */
function renderFull(cards, finds, pageTextByCard) {
  const lines = [];
  lines.push("# pursue-index — full corpus");
  lines.push("");
  lines.push(
    "Citable archive of the U.S. Department of War PURSUE UAP document releases.",
  );
  lines.push(
    "Source documents are public-domain U.S. Government work; the indexing layer (manifest, OCR transcripts, search) is Apache-2.0.",
  );
  lines.push(`Canonical site: ${SITE_ORIGIN}`);
  lines.push("");

  lines.push("## Project overview");
  lines.push("");
  lines.push(`URL: ${SITE_ORIGIN}/`);
  lines.push("");
  lines.push(
    "pursue-index is a hash-pinned, OCR-indexed archive of declassified UAP documents released by the U.S. Department of War under the Presidential Unsealing & Reporting System for UAP Encounters (PURSUE). Every record links back to its original war.gov artifact; every OCR transcript is page-numbered and citable by `card_id:page`.",
  );
  lines.push("");

  lines.push("## Methodology");
  lines.push("");
  lines.push(`URL: ${SITE_ORIGIN}/methodology`);
  lines.push("");
  lines.push(
    "Every claim on the site traces back to a specific page of a specific document. The pipeline fetches the upstream CSV (war.gov), hashes it, downloads each asset, content-addresses bytes by sha256, OCRs PDF pages with Surya (LLM fallback for low-confidence cases), and builds a manifest committed alongside the code. Tranche events that change upstream bytes are recorded with both versions preserved across primary R2, backup R2, and a NAS tier.",
  );
  lines.push("");

  lines.push("## About");
  lines.push("");
  lines.push(`URL: ${SITE_ORIGIN}/about`);
  lines.push("");
  lines.push(
    "pursue-index is a searchable, citable archive of the U.S. Department of War PURSUE UAP document releases. Every record is hash-pinned to the source CSV; every asset URL resolves directly to the original war.gov artifact. Full-text search runs entirely in the browser — no server, no tracking.",
  );
  lines.push("");

  lines.push("## How to cite");
  lines.push("");
  lines.push(`URL: ${SITE_ORIGIN}/cite`);
  lines.push("");
  lines.push(
    "Cite the original DOW PDF for the contents of a source document. Cite this site (with `card_id` and page) for a transcribed passage as it appears here. Cite the corpus by its manifest snapshot (csv_sha256) for reproducibility.",
  );
  lines.push("");

  lines.push("## Cards");
  lines.push("");
  lines.push(
    `${cards.length} cards across the current corpus. Each card has a canonical URL on this site and a `,
  );
  lines.push(
    "`sameAs` link back to its war.gov artifact. Where OCR text is available, the first page's text is included verbatim below (truncated to ~500 characters).",
  );
  lines.push("");
  for (const card of cards) {
    lines.push(`### ${card.card_id} — ${card.title}`);
    lines.push("");
    const date = card.incident_date || card.release_date || "(undated)";
    lines.push(`- Agency: ${card.agency}`);
    lines.push(`- Date: ${date}`);
    lines.push(`- URL: ${SITE_ORIGIN}/card/${card.card_id}`);
    if (card.asset_url) lines.push(`- Source: ${card.asset_url}`);
    if (card.description) lines.push(`- Description: ${card.description}`);
    const text = pageTextByCard.get(card.card_id);
    if (text) {
      const excerpt = text.replace(/\s+/g, " ").trim().slice(0, 500);
      lines.push("");
      lines.push("Excerpt (page 1):");
      lines.push("");
      lines.push(excerpt);
    }
    lines.push("");
  }

  if (finds.length > 0) {
    lines.push("## Finds");
    lines.push("");
    lines.push(
      `${finds.length} curated reading guides authored from specific cards and pages.`,
    );
    lines.push("");
    for (const f of finds) {
      lines.push(`### ${f.slug} — ${f.meta.title}`);
      lines.push("");
      lines.push(`- URL: ${SITE_ORIGIN}/finds/${f.slug}`);
      lines.push(`- Published: ${f.meta.published}`);
      if (Array.isArray(f.meta.cards) && f.meta.cards.length > 0) {
        lines.push(`- Cards: ${f.meta.cards.join(", ")}`);
      }
      if (f.meta.summary) {
        lines.push("");
        lines.push(f.meta.summary);
      }
      lines.push("");
      lines.push(stripMdx(f.body));
      lines.push("");
    }
  }
  return lines.join("\n");
}

function loadFinds() {
  if (!existsSync(FINDS_DIR)) return [];
  const out = [];
  for (const file of readdirSync(FINDS_DIR)) {
    if (!file.endsWith(".md") && !file.endsWith(".mdx")) continue;
    const slug = file.replace(/\.(md|mdx)$/, "");
    const raw = readFileSync(join(FINDS_DIR, file), "utf8");
    const { meta, body } = parseFrontmatter(raw);
    if (meta.draft === "true" || meta.draft === true) continue;
    out.push({ slug, meta, body });
  }
  // Sort newest-first.
  out.sort((a, b) => String(b.meta.published).localeCompare(String(a.meta.published)));
  return out;
}

function main() {
  const manifest = readJson(MANIFEST_PATH, { cards: [] });
  const cards = Array.isArray(manifest.cards) ? manifest.cards : [];
  const finds = loadFinds();
  const pageTextByCard = buildPageTextLookup();

  const indexBody = renderIndex(cards, finds);
  const fullBody = renderFull(cards, finds, pageTextByCard);

  writeFileSync(OUT_INDEX, indexBody);
  writeFileSync(OUT_FULL, fullBody);

  // eslint-disable-next-line no-console
  console.log(
    `build_llms_txt: wrote ${OUT_INDEX} (${indexBody.length} bytes) and ${OUT_FULL} (${fullBody.length} bytes).`,
  );
}

// Run if invoked directly; export helpers for testing.
const invokedDirectly = (() => {
  if (!process.argv[1]) return false;
  try {
    return resolve(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
})();
if (invokedDirectly) {
  main();
}

export {
  buildPageTextLookup,
  parseFrontmatter,
  renderIndex,
  renderFull,
  stripMdx,
  loadFinds,
};
