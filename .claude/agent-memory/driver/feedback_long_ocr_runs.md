---
name: Long-running pipeline jobs survive Bash tool teardown only with nohup
description: A pursue ocr run launched via Bash run_in_background:true gets SIGTERM'd when the bash tool kills its own background tracker. Use nohup + & + redirect to detach fully.
type: feedback
---

Multi-hour pipeline jobs (Surya full corpus pass, embed full run) need to
survive arbitrary bash-tool actions during the conversation. Lessons:

- `Bash(run_in_background: true)` with a piped `tee` does NOT detach. When
  the bash tool kills its own background-task tracker (e.g., when another
  long bash call starts and shadows it), the SIGTERM propagates to the
  whole pipeline including the `pursue ocr run` process. Lost ~30 min
  of Surya progress this way.
- Use `nohup ... > /tmp/log 2>&1 & echo $!` inside a foreground Bash call
  instead. The Bash call returns in seconds with the PID; the actual
  process is fully detached and survives every subsequent bash-tool
  action including stale `until`-loop watchers being killed.
- For the resume case (need to skip already-done cards without `--force`):
  delete only the `meta.json` files of the cards you want to redo. The
  `_is_done` check in `ocr_card` only looks at `status==ok` in
  `meta.json`, not engine name or freshness. So selectively unlinking
  meta.json for non-target-engine cards lets a second `pursue ocr run`
  pick up exactly where the kill left off.

**Why:** Discovered when the first Surya full pass got killed at 7/116
cards. Had to re-launch under `nohup` to make it survive subsequent
bash actions. Resumed cleanly via the meta.json-unlink trick rather
than redoing the 7 large cards.

**How to apply:** Any future long-running ingest/embed/OCR job:
1. Launch with `nohup ... > /tmp/job.log 2>&1 & echo $!` so the bash
   tool returns instantly and the process is detached.
2. Set up a single `until [ "$(grep -c "done_event" /tmp/job.log)" -ge N ];
   do sleep 120; done` watcher with `run_in_background: true` to be
   notified when the job finishes — but don't pile up multiple watchers.
3. If a long job dies mid-pipeline and you need to resume without
   `--force`, the `meta.json`-unlink trick is the surgical recovery.
