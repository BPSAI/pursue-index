---
name: Voyage API key on free tier blocks live embed runs
description: VOYAGE_API_KEY in .env (`pa-XMhrfxMzgW2j…`) is on the free tier — 3 RPM / 10K TPM. The live `pursue embed run` over the 4153-page corpus fails immediately with `RateLimitError: You have not yet added your payment method`.
type: project
---

The current `VOYAGE_API_KEY` in `.env` is provisioned but no payment
method is attached, which Voyage gates as 3 RPM / 10K TPM. The
`pursue embed run --cost-cap-usd 5` over the full corpus aborts on the
first batch.

**Why:** The user expected the projected $0.13 spend (well under the
200M free-token allowance for voyage-3) to "just work," but the rate
limits gate request frequency independently of token allowance until
billing is configured at https://dashboard.voyageai.com/.

**How to apply:** If asked to run `pursue embed run` against the live
corpus and the run fails with the rate-limit error, surface the issue
to the user — don't try to work around it with throttling/retry, since
even a perfectly-throttled run takes 3+ hours on the free tier and
that's not a useful workaround. Tell the user to add a payment method
on the Voyage dashboard, then re-run.

If a payment method has been added, the Voyage adapter should work
without changes (it uses the SDK's default retry semantics for
transient errors).
