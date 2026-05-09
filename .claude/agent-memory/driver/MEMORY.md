# Driver Memory

> This file is automatically loaded into the Driver agent's system prompt (first 200 lines).
> Record implementation patterns, mock strategies, and coding pitfalls specific to this project.

## Architecture Constraints
- **Lines**: <400 error, <200 warning (test files: <600/<400)
- **Functions**: <50 lines, <15 per file (test files: <30)
- **Imports**: <20 per file (test files: <40)
- Run `bpsai-pair arch check <path>` before completing any task

## TDD Workflow
- One behavior at a time: write failing test → minimal code → refactor → repeat
- Never write all tests upfront
- Run from project root: `python -m pytest tests/ -v`

## Patterns Learned

- [Anthropic OAuth via Claude Code creds](feedback_oauth_for_anthropic.md) — Sonnet hits 429 immediately on Max-tier; default to Haiku for benchmarks/smoke.
- [Worktree CWD vs main repo gotcha](feedback_worktree_cwd.md) — absolute paths to /home/david/projects/pursue-index/ land on main, not the worktree; verify `git status` from the worktree dir.
- [Long-running pipelines need nohup](feedback_long_ocr_runs.md) — Bash run_in_background propagates SIGTERM; nohup + & detaches fully. The `meta.json`-unlink trick lets a kill-resume skip already-done cards without `--force`.
- [Surya emits <b>/<u>/<i> markup](feedback_surya_markup.md) — strip at the search-payload boundary, not in ocr/surya.py; keep raw model output in pages.jsonl.
- [pursue ocr run --engine auto --force re-OCRs everything](feedback_auto_mode_force.md) — for sub-threshold-only LLM cleanup, use scripts/auto_mode_from_cache.py; ~38 min vs ~3-4 h.
- [Voyage free tier blocks live embed](feedback_voyage_free_tier.md) — the VOYAGE_API_KEY in .env has no payment method; user has to add one before `pursue embed run` over the corpus will succeed.
