/**
 * robots.txt content builder for pursue-index.
 *
 * Pulled out of the Astro page so the generated text is unit-testable
 * (and so future operators can audit the policy without diffing an
 * inline string literal). The output is the body of the served
 * `/robots.txt` resource.
 *
 * **Policy (2026-05-17).** pursue-index is a primary-source
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
 * earlier robots.txt because that namespace is the worker's
 * chat/search dispatch and is not browseable.
 *
 * The Disallow section is emitted **before** the Allow section: RFC
 * 9309 says most parsers honor first match, so a training crawler
 * reading top-down hits its own Disallow before any other rule.
 */

/**
 * Bots that Cloudflare's Managed robots.txt already Disallows by
 * default. CF prepends a User-agent block for each of these to every
 * robots.txt served via the CF Managed feature; emitting our own
 * Disallow for the same bot produces a Lighthouse-flagged duplicate
 * User-agent line (functionally a no-op under RFC 9309 first-match
 * but ugly).
 *
 * (2026-05-17): `buildRobotsTxt()` filters AI_BLOCK
 * against this list before rendering, so the surfaced body contains
 * only the bots we add on top of CF Managed (PanguBot, TikTok
 * Spider, FacebookBot, etc.). If CF's upstream Managed list
 * expands, update this constant — view-source on
 * https://pursueindex.com/robots.txt is the authoritative source.
 *
 * AI_ALLOW is intentionally **not** filtered against this list: CF
 * Managed disallows-by-default these bots, so our explicit Allow
 * remains load-bearing. (Though most of CF_MANAGED_BOTS are training
 * crawlers we'd block anyway — Applebot-Extended being the boundary
 * case where the search-purpose variant `Applebot` is in AI_ALLOW.)
 */
export const CF_MANAGED_BOTS: readonly string[] = [
  "Amazonbot",
  "Applebot-Extended",
  "Bytespider",
  "CCBot",
  "ClaudeBot",
  "CloudflareBrowserRenderingCrawler",
  "Google-Extended",
  "GPTBot",
  // CF lowercases this one in its Managed output.
  "meta-externalagent",
] as const;

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
 *
 * NOTE: some bots in this list are ALSO in
 * `CF_MANAGED_BOTS` (CF's Managed robots.txt disallows them by
 * default). Those bots remain in `AI_BLOCK` for source-of-truth
 * clarity — an operator auditing the policy should see the full set
 * we want blocked, regardless of which layer enforces it.
 * `buildRobotsTxt()` filters them out at render time so the served
 * body contains no duplicate User-agent entries. If CF Managed is
 * ever turned off, removing the filter restores the full block list
 * in our body without any other change.
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
 * Compute the AI_BLOCK subset that's NOT already handled by CF
 * Managed robots.txt. Case-insensitive match so CF's lowercased
 * `meta-externalagent` matches our `Meta-ExternalAgent`.
 */
export function effectiveBlockList(): readonly string[] {
  const cfSet = new Set(CF_MANAGED_BOTS.map((n) => n.toLowerCase()));
  return AI_BLOCK.filter((n) => !cfSet.has(n.toLowerCase()));
}

/**
 * Build the robots.txt body.
 *
 * Format (top to bottom):
 *   1. Header comments naming the source-of-truth file + the CF
 *      Managed dedup posture.
 *   2. AI_BLOCK section, filtered to bots NOT already handled by CF
 *      Managed (see `CF_MANAGED_BOTS`). One `User-agent: X /
 *      Disallow: /` block per remaining training crawler. Emitted
 *      first so first-match parsers hit the deny rule before any
 *      other.
 *   3. AI_ALLOW section — one `User-agent: X / Allow: /` block per
 *      surfacing bot. Not filtered: CF Managed disallows-by-default,
 *      so our explicit Allow is what flips those bots back on.
 *   4. `Sitemap:` and `Host:` directives.
 *
 * The wildcard `User-agent: *` block is intentionally NOT emitted.
 * CF Managed renders the canonical wildcard for the zone (with
 * `Allow: /` and `Content-Signal: search=yes,ai-train=no`); ours
 * duplicated it and tripped a Lighthouse SEO warning. The
 * (2026-05-17) decision: defer to CF for the wildcard.
 *
 * Note: this means the earlier `Disallow: /api/` rule is no
 * longer asserted in our body. /api/ remains protected by the
 * worker's routing (it's only a JSON dispatch namespace, not a
 * browseable surface), and a named-bot Disallow can be added
 * directly to AI_BLOCK if a specific crawler ever needs it.
 */
export function buildRobotsTxt(opts: RobotsOptions): string {
  const host = hostOf(opts.siteOrigin);
  const blockList = effectiveBlockList();
  const lines: string[] = [
    "# robots.txt for pursue-index — primary-source UAP document archive.",
    "# Generated by web/src/pages/robots.txt.ts (splits AI-surface vs.",
    "# AI-training bot policy, dedupes against Cloudflare's Managed",
    "# robots.txt disallow list). Edit AI_ALLOW / AI_BLOCK /",
    "# CF_MANAGED_BOTS in web/src/lib/robots.ts to amend policy.",
    "#",
    "# Cloudflare's Managed robots.txt prepends its own Disallow for a",
    "# known set of training bots and renders the canonical wildcard",
    "# block; this body adds the bots Managed doesn't cover and the",
    "# vendor user/search bots we want explicitly allowed.",
    "",
    "# ---- Blocked: AI training-corpus crawlers (non-CF-managed only) ----",
    "# These bots ingest content into LLM pretraining / foundation-model",
    "# training pipelines and are NOT already disallowed by CF Managed.",
    "# Listed first so first-match parsers honor the Disallow before any",
    "# later rule. Mirror these in your bot-management layer (CF Bot",
    "# Management / WAF) — robots.txt is voluntary.",
    "",
  ];
  for (const agent of blockList) {
    pushAgentBlock(lines, agent, "Disallow");
  }
  lines.push("# ---- Allowed: AI search / user-fetcher / archiver bots ----");
  lines.push("# These bots surface our content in user-driven sessions");
  lines.push("# (AI assistants, AI search, regular search) or preserve it");
  lines.push("# (archive.org, Arquivo). CF Managed disallows-by-default;");
  lines.push("# the explicit Allow here flips them back on.");
  lines.push("");
  for (const agent of AI_ALLOW) {
    pushAgentBlock(lines, agent, "Allow");
  }
  lines.push(`Sitemap: ${opts.siteOrigin}/sitemap-index.xml`);
  lines.push(`Host: ${host}`);
  lines.push("");
  return lines.join("\n");
}
