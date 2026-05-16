/**
 * Smoke test for the llms.txt + llms-full.txt build pipeline.
 *
 * Asserts on a small in-process fixture that the renderers produce
 * the expected anchor-stable H2 structure, the per-card excerpt
 * blocks, and the index-style canonical-URL listings. Avoids hitting
 * the live manifest/pages.json so the test is deterministic.
 *
 * Run: `node --test web/scripts/build_llms_txt.test.mjs`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseFrontmatter,
  renderIndex,
  renderFull,
  stripMdx,
} from "./build_llms_txt.mjs";

const CARD_FIXTURE = [
  {
    card_id: "abc123",
    title: "Test Card 1",
    agency: "FBI",
    release_date: "5/8/26",
    incident_date: "6/24/47",
    description: "A test card for smoke testing.",
    asset_url: "https://www.war.gov/example.pdf",
  },
  {
    card_id: "def456",
    title: "Test Card 2",
    agency: "NASA",
    release_date: "5/8/26",
    incident_date: null,
    description: null,
    asset_url: "https://www.war.gov/other.pdf",
  },
];

const FINDS_FIXTURE = [
  {
    slug: "test-find-1",
    meta: {
      title: "Test Find 1",
      summary: "First test finds entry summary.",
      cards: ["abc123"],
      published: "2026-05-09",
    },
    body: "## Body heading\n\nSome content with a <Cite card=\"abc123\" page={5} q=\"test\" /> reference.\n",
  },
];

test("renderIndex emits H2 sections for Meta, Cards, and Finds", () => {
  const out = renderIndex(CARD_FIXTURE, FINDS_FIXTURE);
  assert.match(out, /^## Meta$/m);
  assert.match(out, /^## Cards$/m);
  assert.match(out, /^## Finds$/m);
});

test("renderIndex lists each card with its canonical URL", () => {
  const out = renderIndex(CARD_FIXTURE, FINDS_FIXTURE);
  assert.ok(out.includes("https://pursueindex.com/card/abc123"));
  assert.ok(out.includes("https://pursueindex.com/card/def456"));
  assert.ok(out.includes("Test Card 1"));
  assert.ok(out.includes("Test Card 2"));
});

test("renderIndex lists each finds entry with its canonical URL", () => {
  const out = renderIndex(CARD_FIXTURE, FINDS_FIXTURE);
  assert.ok(out.includes("https://pursueindex.com/finds/test-find-1"));
});

test("renderFull uses anchor-stable H2 structure (same section names always)", () => {
  // The H2 set is the "contract" with the LLM chunker. Reorder is
  // tolerable; the names must be stable across builds.
  const out = renderFull(CARD_FIXTURE, FINDS_FIXTURE, new Map());
  const REQUIRED_H2 = [
    "## Project overview",
    "## Methodology",
    "## About",
    "## How to cite",
    "## Cards",
    "## Finds",
  ];
  for (const h2 of REQUIRED_H2) {
    assert.ok(out.includes(h2), `Missing H2 section: ${h2}`);
  }
});

test("renderFull emits an H3 per card with agency/date/URL and source", () => {
  const out = renderFull(CARD_FIXTURE, FINDS_FIXTURE, new Map());
  assert.match(out, /^### abc123 — Test Card 1$/m);
  assert.match(out, /^### def456 — Test Card 2$/m);
  assert.ok(out.includes("https://pursueindex.com/card/abc123"));
  assert.ok(out.includes("https://www.war.gov/example.pdf"));
  assert.ok(out.includes("Agency: FBI"));
});

test("renderFull truncates OCR excerpts at ~500 chars", () => {
  const longText = "x".repeat(2000);
  const lookup = new Map([["abc123", longText]]);
  const out = renderFull(CARD_FIXTURE, FINDS_FIXTURE, lookup);
  // Confirm the excerpt block appears.
  assert.ok(out.includes("Excerpt (page 1):"));
  // Confirm we don't emit the full 2000 chars verbatim.
  assert.ok(!out.includes("x".repeat(600)));
});

test("renderFull emits H3 per finds entry with body excerpt", () => {
  const out = renderFull(CARD_FIXTURE, FINDS_FIXTURE, new Map());
  assert.match(out, /^### test-find-1 — Test Find 1$/m);
  assert.ok(out.includes("https://pursueindex.com/finds/test-find-1"));
  assert.ok(out.includes("Body heading"));
});

test("parseFrontmatter extracts YAML frontmatter + body", () => {
  const raw = `---
title: "Hello"
summary: "Test summary"
cards:
  - abc123
  - def456
published: 2026-05-09
---
Body content here.
`;
  const { meta, body } = parseFrontmatter(raw);
  assert.equal(meta.title, "Hello");
  assert.equal(meta.summary, "Test summary");
  assert.deepEqual(meta.cards, ["abc123", "def456"]);
  assert.equal(meta.published, "2026-05-09");
  assert.match(body, /^Body content here\./);
});

test("stripMdx removes imports and renders <Cite> as bracket marker", () => {
  const raw = `import Cite from "../../components/Cite.astro";

Text with <Cite card="abc123" page={5} q="example phrase" /> citation.
`;
  const out = stripMdx(raw);
  assert.ok(!out.includes("import Cite"));
  assert.ok(out.includes("[cite: card abc123 p.5 \"example phrase\"]"));
});
