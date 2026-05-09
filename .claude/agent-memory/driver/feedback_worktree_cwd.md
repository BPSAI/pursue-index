---
name: Worktree CWD vs main repo path gotcha
description: Bash tool's working directory may report the worktree path but absolute paths to /home/david/projects/pursue-index/ land on main, not the worktree. Use the worktree absolute path explicitly.
type: feedback
---

The driver agent runs with `cwd` set to the worktree
(`/home/david/projects/pursue-index/.claude/worktrees/agent-XXX/`), but
Read/Write/Edit tools accept absolute paths. Edits to
`/home/david/projects/pursue-index/scripts/foo.py` land on the **main
repo**, not the worktree — they don't show up in the worktree's `git
status` and the worktree branch can't commit them.

**Why:** Discovered after writing 8 new files for the OCR benchmark and
finding the worktree's `git status` empty, while `cd /home/david/...
&& git status` showed all my changes on `main`. Had to copy files over
manually before committing.

**How to apply:**
- Always use the full worktree absolute path for Read/Write/Edit when
  in a worktree session:
  `/home/david/projects/pursue-index/.claude/worktrees/agent-XXX/...`
- Or `cd` into the worktree at the top of every Bash call (the bash
  tool resets cwd between calls, so this needs to be in every command).
- After making file changes, run `git status` from the worktree dir
  early to verify the changes are showing where expected. If they're
  on main, copy them over before committing.
- Files under `/mnt/nas/personal/pursue/` (OCR output) are shared
  between main and worktrees, so OCR pipeline writes don't have this
  problem — only repo files do.
