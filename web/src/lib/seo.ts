/**
 * Schema.org JSON-LD builders for pursue-index.
 *
 * Each function in this module returns a plain JS object that the
 * `JsonLd.astro` component serializes into a `<script type="application/ld+json">`
 * tag. The schema choices are oriented for AI Overviews / LLM-citation
 * surfacing (the GEO discipline documented in
 * `.paircoder/plans/sprint-roadmap-2026-05-16.md`), not for traditional
 * SEO ranking signals.
 *
 * **Posture:** pursue-index is a primary-source archive. NO marketing
 * copy, NO promotional language, NO synthetic fields. All values
 * populated here come from real corpus data or factual descriptors of
 * the archive's structure. The `seo.test.ts` guard test runs a banned
 * word list against every builder's output.
 */

export const SITE_ORIGIN = "https://pursueindex.com";

/** Schema-context-tagged JSON object. */
export type JsonLdObject = {
  "@context"?: string;
  "@type": string;
  [key: string]: unknown;
};

// ---------------------------------------------------------------------------
// Organization
// ---------------------------------------------------------------------------

export function organizationJsonLd(): JsonLdObject {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: "pursue-index",
    url: SITE_ORIGIN,
    description:
      "Citable archive of the U.S. Department of War PURSUE UAP document releases.",
    sameAs: [
      "https://github.com/BPSAI/pursue-index",
    ],
  };
}

// ---------------------------------------------------------------------------
// WebSite (with SearchAction)
// ---------------------------------------------------------------------------

export function websiteJsonLd(): JsonLdObject {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: "PURSUE://INDEX",
    url: SITE_ORIGIN,
    description:
      "Searchable archive of the U.S. Department of War PURSUE UAP document releases.",
    potentialAction: {
      "@type": "SearchAction",
      target: {
        "@type": "EntryPoint",
        urlTemplate: `${SITE_ORIGIN}/search?q={search_term_string}`,
      },
      "query-input": "required name=search_term_string",
    },
  };
}

// ---------------------------------------------------------------------------
// Dataset
// ---------------------------------------------------------------------------

export interface DatasetInputs {
  cardCount: number;
  ocrPageCount: number;
  lastTrancheDate: string;
  release01Date: string;
}

export function datasetJsonLd(inputs: DatasetInputs): JsonLdObject {
  return {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: "PURSUE Release 01 — Department of War UAP Document Corpus (pursue-index)",
    description:
      `Hash-pinned, OCR-indexed archive of U.S. Department of War PURSUE UAP document releases. ${inputs.cardCount} cards across ${inputs.ocrPageCount} OCR'd pages; sha-256-addressed bytes, page-level citations, machine-readable manifest.`,
    url: SITE_ORIGIN,
    identifier: `${SITE_ORIGIN}/data/manifest.json`,
    keywords: [
      "UAP",
      "UFO",
      "Department of War",
      "primary sources",
      "declassified documents",
      "OCR",
      "PURSUE Release 01",
      "FBI",
      "NASA",
      "Department of State",
      "FOIA",
    ],
    // Dual licensing: Apache-2.0 for code/indexing layer; public-domain
    // for the underlying U.S. Government work.
    license: [
      "https://www.apache.org/licenses/LICENSE-2.0",
      "https://www.usa.gov/government-works",
    ],
    creator: {
      "@type": "Organization",
      name: "pursue-index",
      url: SITE_ORIGIN,
    },
    datePublished: inputs.release01Date,
    dateModified: inputs.lastTrancheDate,
    isAccessibleForFree: true,
    distribution: [
      {
        "@type": "DataDownload",
        encodingFormat: "application/json",
        contentUrl: `${SITE_ORIGIN}/data/manifest.json`,
      },
      {
        "@type": "DataDownload",
        encodingFormat: "application/json",
        contentUrl: `${SITE_ORIGIN}/data/pages.json`,
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// DigitalDocument (card pages)
// ---------------------------------------------------------------------------

export interface CardLike {
  card_id: string;
  title: string;
  agency: string;
  release_date?: string | null;
  asset_url?: string | null;
  asset_filename?: string | null;
}

/** Maximum bytes of OCR text embedded in the DigitalDocument JSON-LD. */
const MAX_TEXT_BYTES = 5000;

export function digitalDocumentJsonLd(
  card: CardLike,
  textSlice: string,
): JsonLdObject {
  const sameAs: string[] = [];
  if (card.asset_url) sameAs.push(card.asset_url);

  const out: JsonLdObject = {
    "@context": "https://schema.org",
    "@type": "DigitalDocument",
    identifier: card.card_id,
    name: card.title,
    url: `${SITE_ORIGIN}/card/${card.card_id}`,
    sameAs,
    creator: {
      "@type": "GovernmentOrganization",
      name: card.agency,
    },
    isAccessibleForFree: true,
    inLanguage: "en",
    text: textSlice.length > MAX_TEXT_BYTES
      ? textSlice.slice(0, MAX_TEXT_BYTES)
      : textSlice,
  };
  if (card.release_date) {
    // Best-effort date normalization: the manifest's release_date is in
    // M/D/YY (US) shape. We pass it through unchanged in the schema —
    // a strict ISO normalizer would mask real provenance data.
    out.datePublished = card.release_date;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Article (finds entries)
// ---------------------------------------------------------------------------

export interface FindsEntryLike {
  id: string;
  data: {
    title: string;
    summary: string;
    cards: string[];
    published: Date;
    updated?: Date;
    tags?: string[];
    author?: string;
  };
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function articleJsonLd(entry: FindsEntryLike): JsonLdObject {
  const published = isoDate(entry.data.published);
  const modified = entry.data.updated ? isoDate(entry.data.updated) : published;
  const authorName = entry.data.author ?? "pursue-index";
  return {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: entry.data.title,
    description: entry.data.summary,
    url: `${SITE_ORIGIN}/finds/${entry.id}`,
    datePublished: published,
    dateModified: modified,
    author: {
      "@type": "Organization",
      name: authorName,
      url: SITE_ORIGIN,
    },
    publisher: {
      "@type": "Organization",
      name: "pursue-index",
      url: SITE_ORIGIN,
    },
    keywords: entry.data.tags ?? [],
    citation: entry.data.cards.map((id) => ({
      "@type": "CreativeWork",
      "@id": `${SITE_ORIGIN}/card/${id}`,
      url: `${SITE_ORIGIN}/card/${id}`,
      identifier: id,
    })),
    isAccessibleForFree: true,
    inLanguage: "en",
  };
}

// ---------------------------------------------------------------------------
// BreadcrumbList
// ---------------------------------------------------------------------------

export interface Crumb {
  name: string;
  url: string;
}

export function breadcrumbJsonLd(crumbs: Crumb[]): JsonLdObject {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem",
      position: i + 1,
      name: c.name,
      item: c.url.startsWith("http") ? c.url : `${SITE_ORIGIN}${c.url}`,
    })),
  };
}

// ---------------------------------------------------------------------------
// Speakable
// ---------------------------------------------------------------------------

export function speakableJsonLd(cssSelectors: string[]): JsonLdObject {
  if (cssSelectors.length === 0) {
    throw new Error("speakableJsonLd requires at least one CSS selector");
  }
  return {
    "@context": "https://schema.org",
    "@type": "SpeakableSpecification",
    cssSelector: cssSelectors,
  };
}
