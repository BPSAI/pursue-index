# Security

## Reporting a vulnerability

Email security@bpsaisoftware.com. Include enough detail to reproduce
(URLs, payloads, expected vs. observed behavior). We aim to acknowledge
within 72 hours.

## Threat model — public-corpus deployment

This repository is deployed at https://pursueindex.com against a corpus
of public-domain U.S. Government documents. The threat model assumes:

- All indexed content is intentionally public.
- The retrieval API (`/api/retrieve`) is read-only and uncapped.
- The chat API (`/api/chat`) is read-only and rate-limited per-IP.
- `card_id` derivation (`sha256(asset_url || title)[:16]`) is publicly
  documented because no enumeration of the index reveals anything not
  already public.

### Surface protections in place

| Concern              | Mitigation                                                                                      |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| Browser CSRF         | CORS allowlist on `/api/*` (only `pursueindex.com` and `www.pursueindex.com`)                    |
| Anonymous abuse      | Per-IP daily cap (`RATE_LIMIT` in `worker/chat_kv.js`) + global daily $ cap (`DAILY_BUDGET_USD`) |
| Prompt injection     | System prompt enforces inline `[card_id:page]` citations and abstention on off-corpus queries    |
| Upstream key leakage | Anthropic / Voyage keys live in Worker secrets; BYOK keys go browser → Anthropic directly        |
| OCR poisoning        | Surya markup is stripped at the search-payload boundary (`pages.jsonl` keeps raw model output)   |

## Deploying this codebase against a non-public corpus

If you fork this codebase and index private, restricted, or otherwise
non-public documents, the following items in the public surface must be
reviewed and likely removed before going live:

1. **`card_id` derivation in `web/src/pages/api.astro` and `web/src/pages/cite.astro`.**
   The string `sha256(asset_url || title)[:16]` is publicly documented.
   For a private corpus, knowing the derivation lets an attacker
   pre-compute IDs from leaked URLs/titles and probe `/card/<id>`
   without going through the search surface. Remove the derivation
   sentence; document the format only as "16-char hex" without the
   recipe. Consider also salting the hash with a deployment-private
   value so leaked URLs don't grant ID-guessing capability.
2. **Citation contract section of `/api`.** Currently encourages clients
   to parse `[card_id:page]` markers and resolve them at
   `https://pursueindex.com/card/<card_id>#page-<n>`. For a non-public
   deployment, evaluate whether unauthenticated `/card/<id>` access is
   appropriate, or whether card pages should require authentication.
3. **`/api/retrieve` rate posture.** The doc states "uncapped (read-only,
   ~free)". For a non-public corpus, retrieval should almost certainly
   be authenticated and rate-limited. Read access still leaks corpus
   content.
4. **Snippet content in `/api/retrieve` responses.** The endpoint returns
   `snippet` and `page_text` fields. For a non-public corpus, ensure the
   underlying documents permit this surface — `page_text` is the full
   page OCR.
5. **Anthropic / Voyage API keys.** The deployed Worker uses
   `env.ANTHROPIC_API_KEY` and `env.VOYAGE_API_KEY` as Cloudflare Worker
   secrets. Confirm secret rotation policy and audit who can read
   Worker logs (those logs include CF-Connecting-IP).

## Worker constants — current values

The `/api` documentation page imports these at build time and asserts
parity in CI (`web/scripts/test-api-page.mjs`). Constants live in
`worker/chat_kv.js` and `worker/chat.js`:

| Constant              | Source                  | Effect                                                |
| --------------------- | ----------------------- | ----------------------------------------------------- |
| `RATE_LIMIT`          | `worker/chat_kv.js`     | Per-IP daily cap on `/api/chat`                       |
| `DAILY_BUDGET_USD`    | `worker/chat_kv.js`     | Global daily $ cap; degrades to BYOK-only on overrun  |
| `CACHE_TTL_SECONDS`   | `worker/chat_kv.js`     | Semantic-cache TTL on chat responses                  |
| `DEFAULT_MODEL`       | `worker/chat.js`        | Anthropic model for `/api/chat`                       |
| `DEFAULT_K`, `MAX_K`  | `worker/retrieve.js`    | Top-k bounds on `/api/retrieve`                       |
| `SCORE_THRESHOLD`     | `worker/retrieve.js`    | Cosine threshold below which results are filtered out |

Changing any of these on the worker side requires a corresponding
update to `web/src/pages/api.astro`; CI will fail otherwise.
