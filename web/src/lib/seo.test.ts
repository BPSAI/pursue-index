/**
 * Tests for the schema.org JSON-LD builders.
 *
 * Each builder is a pure function from typed input → JSON-LD object.
 * The component layer (`JsonLd.astro`) is responsible for serializing
 * and injecting the script tag; tests at this level assert the shape
 * of the schema, the @context/@type values, and that required fields
 * are populated from real data (no synthetic content).
 *
 * Run with: `node --test src/lib/seo.test.ts`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  organizationJsonLd,
  websiteJsonLd,
  datasetJsonLd,
  digitalDocumentJsonLd,
  articleJsonLd,
  breadcrumbJsonLd,
  speakableJsonLd,
  itemListJsonLd,
} from "./seo.ts";

const SITE = "https://pursueindex.com";

// ---------------- Organization ----------------

test("organizationJsonLd uses schema.org @context and Organization @type", () => {
  const ld = organizationJsonLd();
  assert.equal(ld["@context"], "https://schema.org");
  assert.equal(ld["@type"], "Organization");
});

test("organizationJsonLd names the project + url + sameAs without marketing copy", () => {
  const ld = organizationJsonLd();
  assert.equal(ld.name, "pursue-index");
  assert.equal(ld.url, SITE);
  // sameAs anchors the org identity to the GitHub repo (factual link,
  // no promotional framing).
  assert.ok(Array.isArray(ld.sameAs));
  assert.ok(ld.sameAs.some((u: string) => u.includes("github.com/BPSAI/pursue-index")));
});

// ---------------- WebSite ----------------

test("websiteJsonLd declares a WebSite with a SearchAction", () => {
  const ld = websiteJsonLd();
  assert.equal(ld["@type"], "WebSite");
  assert.equal(ld.url, SITE);
  assert.ok(ld.potentialAction);
  assert.equal(ld.potentialAction["@type"], "SearchAction");
  // The target is a URL template with a `{search_term_string}` token —
  // this is the schema.org SearchAction convention.
  assert.match(
    ld.potentialAction.target.urlTemplate,
    /search\?q=\{search_term_string\}/,
  );
  assert.equal(
    ld.potentialAction["query-input"],
    "required name=search_term_string",
  );
});

// ---------------- Dataset ----------------

test("datasetJsonLd declares the corpus as a Dataset (primary schema)", () => {
  const ld = datasetJsonLd({
    cardCount: 158,
    ocrPageCount: 4161,
    lastTrancheDate: "2026-05-15",
    release01Date: "2026-05-08",
  });
  assert.equal(ld["@type"], "Dataset");
  assert.equal(ld.url, SITE);
  // Keywords are factual descriptors, not promotional.
  assert.ok(Array.isArray(ld.keywords));
  assert.ok(ld.keywords.length > 0);
});

test("datasetJsonLd includes dual licensing (Apache-2.0 code + public-domain data)", () => {
  const ld = datasetJsonLd({
    cardCount: 158,
    ocrPageCount: 4161,
    lastTrancheDate: "2026-05-15",
    release01Date: "2026-05-08",
  });
  // The schema.org `license` field can be a URL or array; we emit
  // both anchors so consumers can resolve either.
  const license = Array.isArray(ld.license) ? ld.license : [ld.license];
  assert.ok(license.some((u: string) => /apache.*2\.0/i.test(u)));
  // Public-domain anchor for the source documents themselves.
  assert.ok(license.some((u: string) => /publicdomain|usa\.gov|publicaccess/i.test(u)));
});

test("datasetJsonLd publishes the release-01 date and updates with last tranche", () => {
  const ld = datasetJsonLd({
    cardCount: 158,
    ocrPageCount: 4161,
    lastTrancheDate: "2026-05-15",
    release01Date: "2026-05-08",
  });
  assert.equal(ld.datePublished, "2026-05-08");
  assert.equal(ld.dateModified, "2026-05-15");
});

test("datasetJsonLd distribution lists machine-readable endpoints", () => {
  const ld = datasetJsonLd({
    cardCount: 158,
    ocrPageCount: 4161,
    lastTrancheDate: "2026-05-15",
    release01Date: "2026-05-08",
  });
  assert.ok(Array.isArray(ld.distribution));
  assert.ok(ld.distribution.length > 0);
  for (const d of ld.distribution) {
    assert.equal(d["@type"], "DataDownload");
    assert.ok(typeof d.contentUrl === "string");
    assert.ok(typeof d.encodingFormat === "string");
  }
});

// ---------------- DigitalDocument ----------------

const CARD_FIXTURE = {
  card_id: "4844321219e306af",
  title: "FBI 62-HQ-83894 Section 2",
  agency: "FBI",
  release_date: "5/8/26",
  asset_url: "https://www.war.gov/medialink/ufo/release_1/example.pdf",
  asset_filename: "example.pdf",
};

test("digitalDocumentJsonLd carries identifier, sameAs (war.gov), and creator", () => {
  const ld = digitalDocumentJsonLd(CARD_FIXTURE, "First 500 chars of OCR text…");
  assert.equal(ld["@type"], "DigitalDocument");
  assert.equal(ld.identifier, "4844321219e306af");
  // sameAs anchors the document back to its upstream artifact for
  // disambiguation across catalogs.
  assert.ok(Array.isArray(ld.sameAs));
  assert.ok(ld.sameAs.includes(CARD_FIXTURE.asset_url));
  // Creator is the originating agency, modeled as GovernmentOrganization.
  assert.equal(ld.creator["@type"], "GovernmentOrganization");
  assert.equal(ld.creator.name, "FBI");
});

test("digitalDocumentJsonLd includes canonical url and text slice", () => {
  const ld = digitalDocumentJsonLd(CARD_FIXTURE, "OCR text first 5KB");
  assert.equal(ld.url, `${SITE}/card/4844321219e306af`);
  assert.equal(ld.text, "OCR text first 5KB");
});

test("digitalDocumentJsonLd truncates text at 5KB to keep payload sane", () => {
  // Schema-shaped payloads should not balloon — 5KB of representative
  // text is enough for AI surfacing without page-bloat.
  const long = "x".repeat(10000);
  const ld = digitalDocumentJsonLd(CARD_FIXTURE, long);
  assert.ok(ld.text.length <= 5000);
});

// ---------------- Article ----------------

const FINDS_FIXTURE = {
  id: "kenneth-arnold-june-24-1947",
  data: {
    title: "Kenneth Arnold, June 24 1947 — In His Own Words",
    summary: "The pilot's written statement, as filed in the FBI record.",
    cards: ["4844321219e306af"],
    published: new Date("2026-05-09T00:00:00Z"),
    updated: undefined as Date | undefined,
    tags: ["fbi", "1947"],
  },
};

test("articleJsonLd populates Article with author, dates, and citation array", () => {
  const ld = articleJsonLd(FINDS_FIXTURE);
  assert.equal(ld["@type"], "Article");
  assert.equal(ld.headline, FINDS_FIXTURE.data.title);
  assert.equal(ld.datePublished, "2026-05-09");
  // No `updated` provided → dateModified === datePublished.
  assert.equal(ld.dateModified, "2026-05-09");
  // Default author: pursue-index. The shape is a typed Organization
  // reference; AI Overviews prefers authored content.
  assert.equal(ld.author.name, "pursue-index");
});

test("articleJsonLd.citation links to primary card URLs", () => {
  const ld = articleJsonLd(FINDS_FIXTURE);
  assert.ok(Array.isArray(ld.citation));
  assert.equal(ld.citation.length, 1);
  assert.equal(ld.citation[0]["@type"], "CreativeWork");
  assert.equal(ld.citation[0].url, `${SITE}/card/4844321219e306af`);
});

test("articleJsonLd uses updated date when frontmatter sets it", () => {
  const withUpdate = {
    ...FINDS_FIXTURE,
    data: { ...FINDS_FIXTURE.data, updated: new Date("2026-05-16T00:00:00Z") },
  };
  const ld = articleJsonLd(withUpdate);
  assert.equal(ld.datePublished, "2026-05-09");
  assert.equal(ld.dateModified, "2026-05-16");
});

// ---------------- BreadcrumbList ----------------

test("breadcrumbJsonLd produces a positional list with @type ListItem", () => {
  const ld = breadcrumbJsonLd([
    { name: "Index", url: "/" },
    { name: "Card", url: "/card/abc123" },
  ]);
  assert.equal(ld["@type"], "BreadcrumbList");
  assert.equal(ld.itemListElement.length, 2);
  assert.equal(ld.itemListElement[0]["@type"], "ListItem");
  assert.equal(ld.itemListElement[0].position, 1);
  assert.equal(ld.itemListElement[1].position, 2);
  // URLs are emitted as absolute (schema.org best practice; relative
  // paths are tolerated but disambiguation prefers absolute).
  assert.equal(ld.itemListElement[0].item, `${SITE}/`);
  assert.equal(ld.itemListElement[1].item, `${SITE}/card/abc123`);
});

test("breadcrumbJsonLd preserves already-absolute URLs", () => {
  const ld = breadcrumbJsonLd([
    { name: "Index", url: `${SITE}/` },
  ]);
  assert.equal(ld.itemListElement[0].item, `${SITE}/`);
});

// ---------------- Speakable ----------------

test("speakableJsonLd wraps CSS selectors for voice-assistant surfaces", () => {
  const ld = speakableJsonLd(["#summary", "#tldr"]);
  assert.equal(ld["@type"], "SpeakableSpecification");
  assert.deepEqual(ld.cssSelector, ["#summary", "#tldr"]);
});

test("speakableJsonLd requires at least one selector (defensive)", () => {
  assert.throws(() => speakableJsonLd([]), /at least one/i);
});

// ---------------- ItemList (crawler-visible card enumeration) ----------------
//
// The homepage dropped its inline cards prop to cut
// DOM size from 695 KB → 26 KB, and CardExplorer now fetches
// /data/cards-summary.json at runtime. AI crawlers + search engines
// without JS execution would see EMPTY cards — regressing the earlier
// GEO win. ItemList JSON-LD enumerates card_id + title + canonical URL
// at SSR time so crawlers parse the structured-data block as the
// canonical card enumeration. Users still get the runtime-fetched grid.

test("itemListJsonLd produces an ItemList with numberOfItems matching input length", () => {
  const ld = itemListJsonLd([
    { id: "aaaa", name: "Card A", url: "https://pursueindex.com/card/aaaa" },
    { id: "bbbb", name: "Card B", url: "https://pursueindex.com/card/bbbb" },
  ]);
  assert.equal(ld["@context"], "https://schema.org");
  assert.equal(ld["@type"], "ItemList");
  assert.equal(ld.numberOfItems, 2);
});

test("itemListJsonLd itemListElement is a position-indexed ListItem array", () => {
  const ld = itemListJsonLd([
    { id: "aaaa", name: "Card A", url: "https://pursueindex.com/card/aaaa" },
    { id: "bbbb", name: "Card B", url: "https://pursueindex.com/card/bbbb" },
  ]);
  assert.ok(Array.isArray(ld.itemListElement));
  assert.equal(ld.itemListElement.length, 2);
  // Schema.org convention: position is 1-based.
  assert.equal(ld.itemListElement[0]["@type"], "ListItem");
  assert.equal(ld.itemListElement[0].position, 1);
  assert.equal(ld.itemListElement[0].name, "Card A");
  assert.equal(ld.itemListElement[0].url, "https://pursueindex.com/card/aaaa");
  assert.equal(ld.itemListElement[1].position, 2);
  assert.equal(ld.itemListElement[1].name, "Card B");
});

test("itemListJsonLd handles the empty-input case (no crash, numberOfItems 0)", () => {
  const ld = itemListJsonLd([]);
  assert.equal(ld.numberOfItems, 0);
  assert.deepEqual(ld.itemListElement, []);
});

// ---------------- No marketing copy guard ----------------

test("none of the builders emit promotional language", () => {
  // pursue-index posture: primary-source archive, no marketing copy.
  // This guard test runs every builder over a representative input
  // set and asserts none of the rendered strings contain words from
  // a banned list. If a future change adds promo phrasing to a
  // builder default, this test fails loudly.
  const BANNED = [
    "best",
    "leading",
    "ultimate",
    "revolutionary",
    "premier",
    "world-class",
    "cutting-edge",
    "innovative",
    "unparalleled",
  ];
  const samples = [
    organizationJsonLd(),
    websiteJsonLd(),
    datasetJsonLd({
      cardCount: 158,
      ocrPageCount: 4161,
      lastTrancheDate: "2026-05-15",
      release01Date: "2026-05-08",
    }),
    digitalDocumentJsonLd(CARD_FIXTURE, "OCR slice"),
    articleJsonLd(FINDS_FIXTURE),
    itemListJsonLd([
      { id: "aaaa", name: "Card A", url: "https://pursueindex.com/card/aaaa" },
    ]),
  ];
  const serialized = JSON.stringify(samples).toLowerCase();
  for (const word of BANNED) {
    assert.ok(
      !serialized.includes(word),
      `Found banned promotional word ${JSON.stringify(word)} in JSON-LD output`,
    );
  }
});
