/**
 * robots.txt content builder for pursue-index.
 *
 * Pulled out of the Astro page so the generated text is unit-testable
 * (and so future operators can audit the policy without diffing an
 * inline string literal). The output is the body of the served
 * `/robots.txt` resource.
 *
 * **Policy (Sprint 1.1, 2026-05-17).** pursue-index is a primary-source
 * archive. We want our content *surfaced* by AI assistants, AI search,
 * regular search, and preservation archivers — but we explicitly do
 * *not* want the corpus pulled into LLM pretraining or generic
 * training-data licensing pipelines. Two typed lists encode this:
 *
 *   - `AI_ALLOW` — bots whose stated purpose is to surface our content
 *     to a user's query (user-fetchers, search bots, archivers).
 *   - `AI_BLOCK` — bots whose stated purpose is bulk corpus ingestion
 *     for model training.
 *
 * Many vendors ship two separate user-agents — one for user-driven
 * fetching (Allow) and one for training (Block). Both ends of each
 * pair are spelled out so the policy is unambiguous to any parser.
 * The `/api/` Disallow at the wildcard level is preserved from the
 * pre-Sprint-1 robots.txt because that namespace is the worker's
 * chat/search dispatch and is not browseable.
 *
 * The Disallow section is emitted **before** the Allow section: RFC
 * 9309 says most parsers honor first match, so a training crawler
 * reading top-down hits its own Disallow before any other rule.
 */

/**
 * AI / search crawlers explicitly ALLOWED to index pursue-index.
 *
 * Selection rule: the bot's stated purpose is on-demand fetching to
 * surface our content in a user's AI assistant / AI search / regular
 * search result, OR it's an archiver (preservation).
 */
export const AI_ALLOW: readonly string[] = [
  // OpenAI — user/search bots (training bot is GPTBot, in AI_BLOCK)
  "ChatGPT-User",
  "OAI-SearchBot",
  // Anthropic — user/search bots (training bot is ClaudeBot, in AI_BLOCK)
  "Claude-User",
  "Claude-SearchBot",
  // Google — Search; Google-Extended (Gemini training opt-out) is in AI_BLOCK
  "Googlebot",
  // Microsoft / Bing — Bing search index also feeds Copilot
  "Bingbot",
  // Apple — Applebot (search/Siri); Applebot-Extended (training opt-out) is in AI_BLOCK
  "Applebot",
  // Perplexity
  "PerplexityBot",
  "Perplexity-User",
  // DuckDuckGo
  "DuckAssistBot",
  // Mistral
  "MistralAI-User",
  // Meta — user-triggered fetcher only; Meta-ExternalAgent + FacebookBot in AI_BLOCK
  "Meta-ExternalFetcher",
  // Huawei — Petal Search; PanguBot (training) in AI_BLOCK
  "PetalBot",
  // Amazon — granular (operator decision 2026-05-17): allow user/search bots,
  // block Amazonbot
  "Amzn-SearchBot",
  "Amzn-User",
  // Google Vertex — opt-in customer RAG indexing (operator decision: Allow)
  "Google-CloudVertexBot",
  // ProRata — pay-publishers RAG (operator decision: Allow)
  "ProRataInc",
  // Cloudflare — operator-described "well-behaved, customer-controlled
  // via Browser Rendering /crawl endpoint"
  "Cloudflare Crawler",
  // Agent browser-as-a-service (user-triggered)
  "Anchor Browser",
  "Manus Bot",
  // Archivers — preservation, not training
  "archive.org_bot",
  "Arquivo Web Crawler",
] as const;

/**
 * AI / training crawlers explicitly BLOCKED from indexing pursue-index.
 *
 * Selection rule: the bot's stated purpose is bulk corpus ingestion for
 * LLM pretraining, foundation-model training, or generic training-data
 * licensing — i.e., the content goes into model weights, not into a
 * citation answer for a user's query.
 */
export const AI_BLOCK: readonly string[] = [
  // OpenAI training crawler
  "GPTBot",
  // Anthropic training crawler
  "ClaudeBot",
  // Google AI training opt-out (separate UA from Googlebot Search)
  "Google-Extended",
  // Apple AI training opt-out (separate UA from Applebot Search)
  "Applebot-Extended",
  // Huawei training crawler (separate UA from PetalBot Search)
  "PanguBot",
  // ByteDance — both training crawlers
  "Bytespider",
  "TikTok Spider",
  // Common Crawl — largest LLM pretraining dataset
  "CCBot",
  // Meta training crawlers (user fetcher Meta-ExternalFetcher is in AI_ALLOW)
  "Meta-ExternalAgent",
  "FacebookBot",
  // Amazon general crawler — operator decision: Block, prefer granular
  // Amzn-SearchBot/Amzn-User Allow
  "Amazonbot",
  // Knowledge-graph training data extractor
  "Diffbot",
  // Image training crawlers (relevant — pursue-index is image-heavy)
  "ImagesiftBot",
  "img2dataset",
  // Cohere training crawler
  "cohere-training-data-crawler",
  // Operator decisions 2026-05-17 — Terracotta + Timpibot flipped to Block
  "Terracotta Bot",
  "Timpibot",
  // Operator decision: Novellum Block (vendor docs thin; conservative)
  "Novellum AI Crawl",
] as const;

export interface RobotsOptions {
  siteOrigin: string;
}

function hostOf(siteOrigin: string): string {
  try {
    return new URL(siteOrigin).host;
  } catch {
    return siteOrigin.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }
}

function pushAgentBlock(
  lines: string[],
  agent: string,
  action: "Allow" | "Disallow",
): void {
  lines.push(`User-agent: ${agent}`);
  lines.push(`${action}: /`);
  lines.push("");
}

/**
 * Build the robots.txt body.
 *
 * Format (top to bottom):
 *   1. Header comments naming the source-of-truth file.
 *   2. AI_BLOCK section — one `User-agent: X / Disallow: /` block per
 *      blocked training crawler. Emitted first so first-match parsers
 *      hit the deny rule before any other.
 *   3. AI_ALLOW section — one `User-agent: X / Allow: /` block per
 *      surfacing bot.
 *   4. Wildcard `User-agent: *` with `Allow: /` + `Disallow: /api/` —
 *      preserves historical behavior for bots not named above.
 *   5. `Sitemap:` and `Host:` directives.
 */
export function buildRobotsTxt(opts: RobotsOptions): string {
  const host = hostOf(opts.siteOrigin);
  const lines: string[] = [
    "# robots.txt for pursue-index — primary-source UAP document archive.",
    "# Generated by web/src/pages/robots.txt.ts (Sprint 1.1 policy split).",
    "# Edit AI_ALLOW / AI_BLOCK in web/src/lib/robots.ts to amend policy.",
    "",
    "# ---- Blocked: AI training-corpus crawlers ----",
    "# These bots ingest content into LLM pretraining / foundation-model",
    "# training pipelines. Listed first so first-match parsers honor the",
    "# Disallow before any later rule. Mirror these in your bot-management",
    "# layer (CF Bot Management / WAF) — robots.txt is voluntary.",
    "",
  ];
  for (const agent of AI_BLOCK) {
    pushAgentBlock(lines, agent, "Disallow");
  }
  lines.push("# ---- Allowed: AI search / user-fetcher / archiver bots ----");
  lines.push("# These bots surface our content in user-driven sessions");
  lines.push("# (AI assistants, AI search, regular search) or preserve it");
  lines.push("# (archive.org, Arquivo). /api/ remains disallowed globally");
  lines.push("# via the wildcard block below.");
  lines.push("");
  for (const agent of AI_ALLOW) {
    pushAgentBlock(lines, agent, "Allow");
  }
  lines.push("# ---- Wildcard fallback (everything else) ----");
  lines.push("User-agent: *");
  lines.push("Allow: /");
  lines.push("Disallow: /api/");
  lines.push("");
  lines.push(`Sitemap: ${opts.siteOrigin}/sitemap-index.xml`);
  lines.push(`Host: ${host}`);
  lines.push("");
  return lines.join("\n");
}
