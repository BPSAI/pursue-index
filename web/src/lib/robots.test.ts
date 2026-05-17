/**
 * Tests for the robots.txt content builder.
 *
 * The dynamic robots.txt page delegates content generation here so it
 * can be unit-tested without spinning up Astro. The builder takes the
 * site origin + a sitemap URL and returns the textual robots.txt body.
 *
 * Sprint 1.1 (2026-05-17) — replaced the single allow-all AI_CRAWLERS
 * list with a typed Allow/Block split that mirrors the operator's
 * stated policy: surface our content (search bots, user-fetchers,
 * archivers) is Allow; training-data ingestion (LLM pretraining
 * crawlers) is Block.
 *
 * Run with: `node --test src/lib/robots.test.ts`
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildRobotsTxt,
  AI_ALLOW,
  AI_BLOCK,
  CF_MANAGED_BOTS,
} from "./robots.ts";

// --- List membership ---------------------------------------------------

test("AI_ALLOW lists the operator-approved surface bots (search/user/archivers)", () => {
  // Each entry is a bot whose stated purpose is to surface our content
  // in an AI assistant / AI search result / regular search result OR
  // is an archiver for preservation. Order here mirrors robots.ts for
  // diff readability.
  const REQUIRED_ALLOW = [
    // OpenAI
    "ChatGPT-User",
    "OAI-SearchBot",
    // Anthropic
    "Claude-User",
    "Claude-SearchBot",
    // Google
    "Googlebot",
    // Microsoft / Bing
    "Bingbot",
    // Apple
    "Applebot",
    // Perplexity
    "PerplexityBot",
    "Perplexity-User",
    // DuckDuckGo
    "DuckAssistBot",
    // Mistral
    "MistralAI-User",
    // Meta — user-fetcher only
    "Meta-ExternalFetcher",
    // Huawei
    "PetalBot",
    // Amazon — granular allow
    "Amzn-SearchBot",
    "Amzn-User",
    // Google Vertex (opt-in customer RAG)
    "Google-CloudVertexBot",
    // ProRata (pay-publishers RAG)
    "ProRataInc",
    // Cloudflare
    "Cloudflare Crawler",
    // Agent browser-as-a-service
    "Anchor Browser",
    "Manus Bot",
    // Archivers
    "archive.org_bot",
    "Arquivo Web Crawler",
  ];
  for (const name of REQUIRED_ALLOW) {
    assert.ok(
      AI_ALLOW.includes(name),
      `Expected AI_ALLOW to include ${JSON.stringify(name)}`,
    );
  }
  assert.equal(AI_ALLOW.length, REQUIRED_ALLOW.length);
});

test("AI_BLOCK lists the operator-rejected training-corpus bots", () => {
  // Each entry is a bot whose stated purpose is bulk corpus ingestion
  // for LLM pretraining, foundation-model training, or generic
  // training-data licensing — content goes into model weights, not
  // into a citation answer for a user's query.
  const REQUIRED_BLOCK = [
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
    "Applebot-Extended",
    "PanguBot",
    "Bytespider",
    "TikTok Spider",
    "CCBot",
    "Meta-ExternalAgent",
    "FacebookBot",
    "Amazonbot",
    "Diffbot",
    "ImagesiftBot",
    "img2dataset",
    "cohere-training-data-crawler",
    "Terracotta Bot",
    "Timpibot",
    "Novellum AI Crawl",
  ];
  for (const name of REQUIRED_BLOCK) {
    assert.ok(
      AI_BLOCK.includes(name),
      `Expected AI_BLOCK to include ${JSON.stringify(name)}`,
    );
  }
  assert.equal(AI_BLOCK.length, REQUIRED_BLOCK.length);
});

test("AI_ALLOW and AI_BLOCK are mutually exclusive (no bot in both lists)", () => {
  // Mutual exclusion guard: a bot must be either surfaced or blocked,
  // never both. The Terracotta Bot case (operator flipped Allow → Block
  // late) is the canonical reason this guard exists.
  const allowSet = new Set(AI_ALLOW);
  const overlap = AI_BLOCK.filter((name) => allowSet.has(name));
  assert.deepEqual(
    overlap,
    [],
    `Found bots present in BOTH AI_ALLOW and AI_BLOCK: ${overlap.join(", ")}`,
  );
});

test("AI_ALLOW and AI_BLOCK have no duplicate entries within their own list", () => {
  // De-dupe guard — easy to miss when manually editing.
  assert.equal(
    new Set(AI_ALLOW).size,
    AI_ALLOW.length,
    "AI_ALLOW contains duplicates",
  );
  assert.equal(
    new Set(AI_BLOCK).size,
    AI_BLOCK.length,
    "AI_BLOCK contains duplicates",
  );
});

// --- Critical-bot spot checks -----------------------------------------

test("critical training bots are in AI_BLOCK", () => {
  // These are the bots whose Allow rule in the prior version was the
  // visible contradiction with operator policy.
  assert.ok(AI_BLOCK.includes("ClaudeBot"), "ClaudeBot must be blocked");
  assert.ok(AI_BLOCK.includes("GPTBot"), "GPTBot must be blocked");
  assert.ok(
    AI_BLOCK.includes("Google-Extended"),
    "Google-Extended must be blocked",
  );
  assert.ok(
    AI_BLOCK.includes("Applebot-Extended"),
    "Applebot-Extended must be blocked",
  );
  assert.ok(AI_BLOCK.includes("PanguBot"), "PanguBot must be blocked");
  assert.ok(AI_BLOCK.includes("CCBot"), "CCBot must be blocked");
  assert.ok(AI_BLOCK.includes("Bytespider"), "Bytespider must be blocked");
  assert.ok(
    AI_BLOCK.includes("Meta-ExternalAgent"),
    "Meta-ExternalAgent must be blocked",
  );
});

test("critical surface bots are in AI_ALLOW", () => {
  // The bots that the operator explicitly wants to keep surfacing
  // content to user-driven sessions.
  assert.ok(
    AI_ALLOW.includes("ChatGPT-User"),
    "ChatGPT-User must be allowed",
  );
  assert.ok(AI_ALLOW.includes("Claude-User"), "Claude-User must be allowed");
  assert.ok(AI_ALLOW.includes("Googlebot"), "Googlebot must be allowed");
  assert.ok(AI_ALLOW.includes("Bingbot"), "Bingbot must be allowed");
  assert.ok(AI_ALLOW.includes("Applebot"), "Applebot must be allowed");
  assert.ok(
    AI_ALLOW.includes("PerplexityBot"),
    "PerplexityBot must be allowed",
  );
  assert.ok(
    AI_ALLOW.includes("archive.org_bot"),
    "archive.org_bot must be allowed",
  );
});

// --- Rendered output --------------------------------------------------

test("buildRobotsTxt emits a Disallow / block for every NON-CF-managed AI_BLOCK entry", () => {
  // Sprint 4a (2026-05-17): bots in CF_MANAGED_BOTS are intentionally
  // filtered out of the rendered body to avoid duplicate User-agent
  // lines with CF's Managed robots.txt. The rendered body must still
  // emit Disallow blocks for the non-overlap set (PanguBot, TikTok
  // Spider, etc.).
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const cfSet = new Set(CF_MANAGED_BOTS.map((n) => n.toLowerCase()));
  const renderedBlock = AI_BLOCK.filter((n) => !cfSet.has(n.toLowerCase()));
  for (const name of renderedBlock) {
    const uaPattern = new RegExp(
      `^User-agent: ${escapeRegex(name)}\\s*$`,
      "m",
    );
    assert.match(body, uaPattern, `Missing User-agent block for ${name}`);
    const idx = body.indexOf(`User-agent: ${name}\n`);
    assert.ok(
      idx >= 0,
      `User-agent: ${name} must be followed by newline`,
    );
    const rest = body.slice(idx);
    assert.match(
      rest.split("\n").slice(0, 3).join("\n"),
      /Disallow: \/$/m,
      `Expected Disallow: / immediately under User-agent: ${name}`,
    );
  }
});

test("buildRobotsTxt emits an Allow / block for every AI_ALLOW entry", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  for (const name of AI_ALLOW) {
    const uaPattern = new RegExp(
      `^User-agent: ${escapeRegex(name)}\\s*$`,
      "m",
    );
    assert.match(body, uaPattern, `Missing User-agent block for ${name}`);
    const idx = body.indexOf(`User-agent: ${name}\n`);
    assert.ok(idx >= 0);
    const rest = body.slice(idx);
    const window = rest.split("\n").slice(0, 3).join("\n");
    assert.match(
      window,
      /Allow: \/$/m,
      `Expected Allow: / immediately under User-agent: ${name}`,
    );
  }
});

test("buildRobotsTxt orders AI_BLOCK entries before AI_ALLOW entries", () => {
  // RFC 9309 says most parsers honor first match. Listing Disallow
  // blocks first means a training crawler reading top-down hits its
  // own rule before hitting any other Allow rule. The first BLOCK
  // entry we render is the first non-CF-managed bot (CF Managed bots
  // are filtered out at render time per Sprint 4a).
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const cfSet = new Set(CF_MANAGED_BOTS.map((n) => n.toLowerCase()));
  const firstRenderedBlock = AI_BLOCK.find((n) => !cfSet.has(n.toLowerCase()));
  assert.ok(firstRenderedBlock, "Sanity: at least one non-CF-managed block bot");
  const firstBlockIdx = body.indexOf(`User-agent: ${firstRenderedBlock}`);
  const firstAllowIdx = body.indexOf(`User-agent: ${AI_ALLOW[0]}`);
  assert.ok(firstBlockIdx >= 0 && firstAllowIdx >= 0);
  assert.ok(
    firstBlockIdx < firstAllowIdx,
    "AI_BLOCK section must come before AI_ALLOW section",
  );
});

test("buildRobotsTxt distinguishes Allow/Disallow correctly for paired bot families", () => {
  // The whole point of Sprint 1.1: a vendor's user bot and its
  // training bot must end up on opposite sides of the policy. Spot
  // check the pairs that survive Sprint 4a's CF-managed dedupe.
  // Disallow-side pairs whose training bot is in CF_MANAGED_BOTS
  // (GPTBot, ClaudeBot, Google-Extended, Applebot-Extended,
  // Amazonbot, Meta-ExternalAgent) are now handled by CF Managed
  // and are not asserted in OUR rendered body.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });

  const pairs: Array<[string, "Allow" | "Disallow"]> = [
    // Pairs whose Disallow side remains in our rendered body:
    ["PanguBot", "Disallow"],
    ["PetalBot", "Allow"],
    // The Allow-side surface bots — none of these are in CF_MANAGED_BOTS,
    // so all remain rendered. Each vendor's training counterpart is
    // intentionally absent (CF Managed handles it).
    ["ChatGPT-User", "Allow"],
    ["Claude-User", "Allow"],
    ["Googlebot", "Allow"],
    ["Applebot", "Allow"],
    ["Meta-ExternalFetcher", "Allow"],
    ["Amzn-SearchBot", "Allow"],
  ];
  for (const [bot, action] of pairs) {
    const idx = body.indexOf(`User-agent: ${bot}\n`);
    assert.ok(idx >= 0, `Missing User-agent: ${bot}`);
    const window = body.slice(idx).split("\n").slice(0, 3).join("\n");
    assert.match(
      window,
      new RegExp(`^${action}: /$`, "m"),
      `Expected ${action}: / for ${bot}, got: ${window}`,
    );
  }
});

test("buildRobotsTxt no longer emits a wildcard or /api/ Disallow (CF Managed handles them)", () => {
  // Sprint 4a (2026-05-17): the wildcard `User-agent: *` block and
  // its `Disallow: /api/` directive were duplicates of CF Managed's
  // canonical wildcard. Removed; CF Managed is now the source-of-
  // truth wildcard. /api/ remains protected by worker routing.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.doesNotMatch(body, /^User-agent: \*$/m);
  assert.doesNotMatch(body, /^Disallow: \/api\//m);
});

test("buildRobotsTxt includes Sitemap and Host directives", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.match(
    body,
    /^Sitemap: https:\/\/pursueindex\.com\/sitemap-index\.xml$/m,
  );
  assert.match(body, /^Host: pursueindex\.com$/m);
});

test("buildRobotsTxt body ends with a trailing newline", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.ok(body.endsWith("\n"), "robots.txt should end with newline");
});

test("buildRobotsTxt accepts a custom siteOrigin", () => {
  const body = buildRobotsTxt({ siteOrigin: "https://example.org" });
  assert.match(
    body,
    /^Sitemap: https:\/\/example\.org\/sitemap-index\.xml$/m,
  );
  assert.match(body, /^Host: example\.org$/m);
});

test("buildRobotsTxt issues exactly one Allow/Disallow rule per emitted bot", () => {
  // Sprint 4a (2026-05-17): wildcard removed; rendered counts are:
  //   Allow: /     = AI_ALLOW.length     (no wildcard Allow)
  //   Disallow: /  = effectiveBlockList  (CF-managed bots filtered out)
  //   Disallow: /api/ = 0                (CF Managed renders the wildcard)
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const allowSlashCount = (body.match(/^Allow: \/$/gm) ?? []).length;
  const disallowSlashCount = (body.match(/^Disallow: \/$/gm) ?? []).length;
  const disallowApiCount = (body.match(/^Disallow: \/api\//gm) ?? []).length;
  const cfSet = new Set(CF_MANAGED_BOTS.map((n) => n.toLowerCase()));
  const renderedBlockCount = AI_BLOCK.filter(
    (n) => !cfSet.has(n.toLowerCase()),
  ).length;
  assert.equal(
    allowSlashCount,
    AI_ALLOW.length,
    "Allow: / count should equal AI_ALLOW.length (no wildcard)",
  );
  assert.equal(
    disallowSlashCount,
    renderedBlockCount,
    "Disallow: / count should match the non-CF-managed AI_BLOCK subset",
  );
  assert.equal(
    disallowApiCount,
    0,
    "Disallow: /api/ should no longer appear (CF Managed handles wildcard)",
  );
});

// --- Sprint 4a B4: CF-managed dedupe ---------------------------------
//
// Cloudflare's Managed robots.txt prepends a Disallow for a set of
// well-known AI/training bots. View-source on
// https://pursueindex.com/robots.txt showed our generated body
// duplicated 8 of those entries (GPTBot, ClaudeBot, Google-Extended,
// CCBot, Bytespider, Applebot-Extended, Amazonbot, wildcard *).
// RFC 9309 first-match wins so the duplicates were functionally a
// no-op, but Lighthouse SEO flagged them. The Sprint 4a change drops
// the bots in CF_MANAGED_BOTS from OUR rendered AI_BLOCK so the
// rendered robots.txt is free of duplicates.

test("CF_MANAGED_BOTS lists the bots Cloudflare's Managed robots.txt handles", () => {
  // Source: live curl https://pursueindex.com/robots.txt (2026-05-17),
  // looking at the CF-prepended User-agent blocks. If CF expands this
  // list upstream, this constant should be updated to match.
  const REQUIRED_CF = [
    "Amazonbot",
    "Applebot-Extended",
    "Bytespider",
    "CCBot",
    "ClaudeBot",
    "CloudflareBrowserRenderingCrawler",
    "Google-Extended",
    "GPTBot",
    "meta-externalagent",
  ];
  for (const name of REQUIRED_CF) {
    assert.ok(
      CF_MANAGED_BOTS.includes(name),
      `Expected CF_MANAGED_BOTS to include ${JSON.stringify(name)}`,
    );
  }
});

test("rendered robots.txt does NOT contain CF_MANAGED_BOTS user-agent blocks", () => {
  // The whole point of the dedupe: our body must not re-disallow the
  // bots that CF Managed already disallows. Lighthouse SEO clears
  // once this stops emitting duplicate User-agent lines.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  for (const name of CF_MANAGED_BOTS) {
    // Case-insensitive match: CF lowercases some agents (e.g.
    // `meta-externalagent`), our list mirrors that. We assert no
    // line `User-agent: <name>` exists in our rendered output for
    // any spelling variant.
    const pattern = new RegExp(
      `^User-agent:\\s*${escapeRegex(name)}\\s*$`,
      "im",
    );
    assert.doesNotMatch(
      body,
      pattern,
      `Rendered robots.txt unexpectedly contains User-agent: ${name} (CF Managed handles it)`,
    );
  }
});

test("rendered robots.txt still contains non-CF-managed AI_BLOCK bots", () => {
  // After dedupe, the bots in AI_BLOCK that are NOT in CF_MANAGED_BOTS
  // remain in the rendered output. This is the non-overlap set
  // (PanguBot, TikTok Spider, FacebookBot, Diffbot, etc.).
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  const cfSet = new Set(CF_MANAGED_BOTS.map((n) => n.toLowerCase()));
  const remaining = AI_BLOCK.filter((n) => !cfSet.has(n.toLowerCase()));
  // Sanity: dedupe didn't remove everything.
  assert.ok(
    remaining.length > 0,
    "AI_BLOCK must have at least one non-CF-managed entry post-dedupe",
  );
  for (const name of remaining) {
    const pattern = new RegExp(
      `^User-agent: ${escapeRegex(name)}\\s*$`,
      "m",
    );
    assert.match(
      body,
      pattern,
      `Missing User-agent block for non-CF-managed ${name}`,
    );
  }
});

test("rendered robots.txt no longer contains the wildcard User-agent: * block", () => {
  // CF Managed renders the canonical wildcard with Allow: / and
  // Content-Signal directives; our wildcard duplicated it. Sprint 4a
  // removes ours entirely. /api/ remains protected by CF's wildcard
  // semantics (RFC 9309 first-match) — if the operator later wants
  // an explicit /api/ Disallow, it must be carried by a NAMED
  // User-agent block, not the wildcard.
  const body = buildRobotsTxt({ siteOrigin: "https://pursueindex.com" });
  assert.doesNotMatch(
    body,
    /^User-agent:\s*\*\s*$/m,
    "Rendered robots.txt should no longer emit the wildcard User-agent: * block (CF Managed renders the canonical one)",
  );
});

// --- helpers ---------------------------------------------------------

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
