---
id: auto-poll-tranches
type: feature
status: shipped (layer 1)
created: 2026-05-09
priority: medium
depends_on: [embed-stage]
---

# Auto-poll for new CSV tranches

> **Status:** Layer 1 (lightweight cron poll) is shipped — see
> `.github/workflows/poll-pursue.yml` and `scripts/poll_pursue.py`.
> Layer 2 (heavy ingest pipeline trigger) is operator-attended by
> design and remains tracked under this plan.

## Why

DOW publishes the PURSUE corpus as a **single CSV updated in place**.
New tranches drop "every few weeks" with no announcement, no RSS, no
versioning. Today, detecting a change requires manually re-running
`pursue scrape run`. That's fine for the launch, but the value of being
the canonical archive is "we have the new stuff before anyone else
notices." Automating the poll closes the gap.

A passing thought worth recording: a determined adversary who sees this
project's methodology page could rewrite war.gov's bot rules to lock us
out. Polling daily-ish from infra they don't control (Cloudflare /
GitHub) gives us early warning if a fetch starts failing — a signal to
investigate, not just an empty diff.

## Architecture

Two-layer split, lightweight + heavy:

### Layer 1 — Daily lightweight poll (Cloudflare Worker scheduled trigger)

A new Worker (or a route on the existing one) runs on a CF Cron Trigger
once a day. Fetches the upstream CSV, computes SHA256, compares to the
last-seen value stored in Workers KV, writes the new value back, and
notifies on change.

- **Cost:** free tier of CF Workers + KV.
- **Pings on change:** webhook → Pushover / Slack / email of choice.
- **No pipeline runs here** — the Worker is read-only, just a watcher.
- **Fail-loud:** if the fetch starts returning non-200 (because the
  upstream changed defenses), the watcher pings "*** scrape blocked"
  before any silent breakage.

### Layer 2 — Heavy pipeline trigger (workstation)

When the watcher pings, the user (or an agent on the workstation, when
GPU is available) runs the full pipeline:

```
pursue scrape run                                      # ~1 sec
pursue download run --manifest data/manifests/latest.json    # minutes
PURSUE_OCR_ENGINE=auto pursue ocr run --manifest …    # minutes-hours
pursue embed run --manifest …                          # minute
scripts/build_search_data.py
scripts/build_embed_data.py
git add data/manifests/latest.json data/csv-archive/   # snapshot manifest
git add web/public/data/{pages,embed_index}.json web/public/data/embeddings.bin
git commit -m "feat(corpus): tranche $(date +%Y-%m-%d) ingest"
git push
```

This wants to be a single shell script
(`scripts/ingest_new_tranche.sh`) so a tired user at midnight runs one
command and everything happens in order with proper failure handling.

## Why split

- The full pipeline needs the local 5090 GPU and NAS access. Can't run
  on Cloudflare or a generic GitHub runner.
- The detection is cheap and should be on infra that's always-on — not
  the workstation, which sleeps.
- Splitting also gives us a better forensic trail. The lightweight poll
  records every check (with timestamp + hash) in KV; even days where
  nothing changed are visible.

## Output convention

CSV archive on NAS already has `data_root/csv-archive/uap-csv-{ts}.csv`
per pass. Add:

- `data/manifests/snapshots/uap-{ts}.json` — committed in repo (small),
  populates the `/diff` page's prior-snapshot list.
- `data/manifests/latest.json` — the always-pointing-at-newest version,
  unchanged.

After Layer 2 runs and produces a new latest, the previous latest moves
to `snapshots/` automatically. The `/diff` page already reads from
that directory; today it's empty, hence the "no prior snapshot yet"
state.

## Acceptance

- CF Cron Trigger fires once daily; KV records the latest CSV hash.
- A change in upstream CSV pings the configured webhook within 15
  minutes.
- A 4xx/5xx from the upstream pings a separate "fetch failed" alert.
- `scripts/ingest_new_tranche.sh` runs the whole pipeline in order,
  fails loudly on any stage, and produces a single git commit when
  everything passes.
- The `/diff` page surfaces the populated state once the second
  snapshot is committed (no UI change needed; it already handles this).

## Open questions

- **Webhook target.** Pushover ($5 one-time, reliable, push to phone)
  vs Slack (already in our stack, requires a workspace) vs email (lowest
  fidelity but most universal). Lean Pushover for the alert pattern.
- **Polling frequency.** Daily is a reasonable starting point. Going
  finer than that risks tripping anti-bot (and burns more KV writes for
  no value when most days don't change).
- **Auto-run Layer 2?** Tempting. Risks: GPU run costs Anthropic dollars,
  bad OCR ships to live, an unexpected tranche format breaks parsing.
  Lean: notification-only at v1; auto-run after the curator has seen
  a few cycles work cleanly.
- **Workstation availability.** If the box is asleep when the poll
  pings, the heavy pass waits until next boot. Acceptable for v1; a
  systemd-suspend wakeup or wake-on-LAN add-on is a v2 thing.

## Out of scope

- Rebuilding `data/manifests/latest.json` on every check — only on
  actual change.
- Polling other archives (Black Vault, NICAP) — covered by the
  novelty-detection plan separately.
- Auto-tweeting / auto-publishing the new tranche — community feed is
  out of scope for v1.
