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

## Documented exceptions

These are dependency-level CVEs that a static scanner will flag but
that we have determined are unexploitable in pursue-index's deployed
runtime. Each entry names a removal trigger so the exception does not
become permanent.

### CVE-2026-1839 — `transformers.Trainer` arbitrary code execution

**Accepted:** 2026-05-09

**Status:** Accepted, unexploitable in pursue-index deployment.

**Audit performed at commit `6373312` against PR #15 (Dependabot
`transformers <5 → <6` bump).**

**Pin:** `transformers>=4.56,<5` in `pyproject.toml [gpu]` extra
(see `pyproject.toml:57-61` — inline rationale at :57-60, pin at :61).

**Why we cannot upgrade:** `surya-ocr 0.17.x` — the GPU OCR engine in
the `[gpu]` extra — fails to import under `transformers >= 5.x`. Until
surya cuts a compatible release, the `<5` ceiling stays. We will
revisit this exception when `surya-ocr` ships a release that supports
`transformers >= 5`.

**Why this CVE is unexploitable for us:**

- pursue-index does not import `transformers.Trainer` anywhere in
  `src/`, `scripts/`, or `tests/`. Audit grep:
  `grep -rn "transformers.Trainer\|TrainingArguments" src/ scripts/ tests/ --include="*.py"`
  returns zero hits as of audit commit `6373312`.
- The OCR pipeline runs Surya's `RecognitionPredictor` +
  `DetectionPredictor` inference paths only. No training, no
  fine-tuning, no `Trainer` instantiation.
- Surya's model weights are bundled with the package and pinned; we
  never load a user-supplied or remote pickled checkpoint.
- The deployed pursueindex.com runtime is a Cloudflare Worker
  (JavaScript). Python — and therefore `transformers` — executes only
  at build/ingest time on operator-controlled hosts, never at request
  time. There is no user-input path that reaches
  `transformers.Trainer`.
- The CVE attack vector requires loading a malicious checkpoint or
  config into `Trainer`. Without `Trainer` instantiation in our code,
  the vector is unreachable.

**Removal trigger:** when `surya-ocr` ships a release that supports
`transformers >= 5.x`, bump both pins in a single PR and delete this
exception entry. (`.github/dependabot.yml` was removed entirely on
2026-05-09 in favor of GitHub's server-side security-update path;
no automated version-bump PRs fire any longer, so the per-package
ignore rule is no longer necessary.)
