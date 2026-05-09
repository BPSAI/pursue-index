---
name: BYOK-from-browser to Anthropic without the SDK
description: Browser → api.anthropic.com direct LLM calls work with raw fetch + the anthropic-dangerous-direct-browser-access header; SDK + dangerouslyAllowBrowser is not required.
type: feedback
---

For BYOK chat surfaces where the user pastes their key into the browser
and we don't want it to ever touch our origin:

- Send POST `https://api.anthropic.com/v1/messages` with headers:
  - `x-api-key: <user key>`
  - `anthropic-version: 2023-06-01`
  - `anthropic-dangerous-direct-browser-access: true`
- The streaming response is the same SSE format as the server-side API
  (event: message_start / content_block_start / content_block_delta /
  content_block_stop / message_delta / message_stop). Parse it inline
  with a 20-line `\n\n`-delimited block reader; you do not need
  `@anthropic-ai/sdk` + `dangerouslyAllowBrowser: true` if you don't
  want the dependency.

**Why:** `pursue-index/web/src/lib/llm-provider.ts`
(`AnthropicBYOKProvider`) intentionally avoids the SDK so the BYOK
path adds zero new npm dependencies and the bundle stays tiny. This
also keeps the Anthropic-SSE parser visibly auditable inside our repo.

**How to apply:** Any future browser-direct LLM path (BYOK Anthropic,
or even an experimental "user-funded preview" mode) should use raw
fetch + the dangerous-direct-browser-access header. Mirror whatever
system prompt the server side uses (the prompt is small enough to
duplicate; reaching back over the network for it adds a failure mode).
