// Workers-KV–backed primitives for the anonymous-tier chat:
//   - checkAndIncrementRate(kv, ip, day?) → per-IP daily counter
//   - cacheKey + readCache/writeCache    → semantic cache (24h TTL)
//   - checkBudget + recordSpend          → daily $ ceiling
//
// All keys are date-bucketed so the namespace self-cleans without an
// LRU pass: every counter/spend record naturally rolls over each UTC day.
// Cache entries get a 24h TTL so even if a query repeats on the next
// day the cache will have expired naturally.

// FIXME(launch): drop RATE_LIMIT to 5 when the splash gate flips off.
// During research preview every visitor holds the magic-link cookie, so the
// 5/day cap was firing on the operator's own dev/test traffic. 100/day is
// the right number for an internal-team pre-launch surface; 5/day is the
// right number for a post-launch anonymous public surface (with BYOK CTA).
export const RATE_LIMIT = 100;
export const DAILY_BUDGET_USD = 100; // global cap before degrade
export const CACHE_TTL_SECONDS = 24 * 60 * 60;

/** Get today's UTC date (YYYY-MM-DD) — overridable for tests. */
export function utcDay(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Rate limit
// ---------------------------------------------------------------------------

function rateKey(ip, day) {
  return `rate:${day}:${ip}`;
}

/**
 * Read-only check of the per-IP daily counter. Does NOT increment.
 *
 * Use this at the top of a chat request to short-circuit a 429 response
 * before doing any retrieval / Anthropic work. The actual increment
 * happens in `incrementRate` AFTER we've decided we're going to spend.
 * Abstention shortcuts and cache hits skip the increment entirely
 * because they don't cost real money.
 */
export async function checkRate(kv, ip, day = utcDay()) {
  const current = parseInt((await kv.get(rateKey(ip, day))) || "0", 10);
  return { allowed: current < RATE_LIMIT, count: current };
}

/**
 * Increment the per-IP daily counter. Call only when the request is
 * about to (or did) spend Anthropic tokens — not for abstentions or
 * cache hits, which are free.
 *
 * Note: Workers KV doesn't have atomic INCR. We accept a tiny race window
 * between get and put — at HN scale the worst case is the limit ticking
 * to N+1 instead of stopping at N for a brief overlap, which is fine.
 */
export async function incrementRate(kv, ip, day = utcDay()) {  
  const key = rateKey(ip, day);
  const current = parseInt((await kv.get(key)) || "0", 10);
  const next = current + 1;
  await kv.put(key, String(next), { expirationTtl: CACHE_TTL_SECONDS });
  return { count: next };
}

/**
 * Backwards-compatible combined check + increment, kept for tests and
 * for any caller that genuinely wants the old semantics. Prefer the
 * split `checkRate` / `incrementRate` pair in new code so abstentions
 * and cache hits don't burn rate budget.
 */
export async function checkAndIncrementRate(kv, ip, day = utcDay()) {
  const check = await checkRate(kv, ip, day);
  if (!check.allowed) return check;
  const inc = await incrementRate(kv, ip, day);
  return { allowed: true, count: inc.count };
}

// ---------------------------------------------------------------------------
// Semantic cache
// ---------------------------------------------------------------------------

/**
 * Cache key = sha256(normalized_query | sorted card_id:page list).
 *
 * Identical retrieval + similar query (after lowercase + whitespace trim)
 * → same cache hit. We don't fuzz-match across embeddings; this catches
 * the "ten variants of Roswell" launch-day duplication without false
 * positives that would mix up similar-but-different questions.
 */
export function cacheKey(query, passages) {
  const norm = (query || "").trim().toLowerCase().replace(/\s+/g, " ");
  const ids = (passages || [])
    .map((p) => `${p.card_id}:${p.page}`)
    .sort()
    .join(",");
  return `cache:${djb2(norm + "|" + ids)}`;
}

function djb2(s) {
  // Small non-cryptographic hash; cache keys don't need collision-resistance.
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(16);
}

export async function readCache(kv, key) {
  return await kv.get(key, "json");
}

export async function writeCache(kv, key, value) {
  await kv.put(key, JSON.stringify(value), { expirationTtl: CACHE_TTL_SECONDS });
}

// ---------------------------------------------------------------------------
// Daily $ budget cap
// ---------------------------------------------------------------------------

function budgetKey(day) {
  return `spend:${day}`;
}

export async function checkBudget(kv, day = utcDay()) {
  const spent = parseFloat((await kv.get(budgetKey(day))) || "0");
  return { allowed: spent < DAILY_BUDGET_USD, spent };
}

export async function recordSpend(kv, day, usd) {
  const key = budgetKey(day);
  const current = parseFloat((await kv.get(key)) || "0");
  const next = current + Math.max(0, usd);
  await kv.put(key, String(next), { expirationTtl: CACHE_TTL_SECONDS * 2 });
}
