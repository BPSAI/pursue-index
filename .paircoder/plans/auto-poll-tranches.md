---
id: auto-poll-tranches
type: feature
status: shipped
created: 2026-04-XX
shipped: 2026-04-XX
priority: high
depends_on: []
---

# Auto-poll for new tranches

> **Status: shipped.** This plan was implemented as
> [`.github/workflows/poll-pursue.yml`](../../.github/workflows/poll-pursue.yml)
> (6-hour scheduled cron + workflow_dispatch trigger). The PDF-fetch
> sentinel was added alongside in PR #28; see
> [`.paircoder/plans/black-vault-reference.md`](./black-vault-reference.md)
> for the parallel reference-corpus poll pattern.
>
> The original plan-document for this feature is no longer required;
> the workflow YAML is canonical.
