# Claude Code Instructions

> **bpsai-pair** — AI-augmented pair programming framework

---

## ⚠️ NON-NEGOTIABLE REQUIREMENTS

These requirements MUST be followed. Failure to follow them is a serious workflow violation.

### 0. Follow TDD for ALL Code Changes

**MANDATORY for any task involving code:**
1. **Write failing tests FIRST** - before writing any implementation code
2. **Write minimal code to pass** - only enough to make tests green
3. **Refactor** - clean up while keeping tests green
4. **Repeat** - for each piece of functionality

**USE THE SKILL:** When implementing code, invoke the `implementing-with-tdd` skill:
```
Use Skill tool with skill: "implementing-with-tdd"
```

**DO NOT:**
- Write implementation code before tests exist
- Write all code then add tests after
- Skip tests for "simple" code

### 1. Update state.md After EVERY Task Completion

**IMMEDIATELY after completing any task**, you MUST update `.paircoder/context/state.md`:
- Mark the task as done in the task list
- Add a session entry under "What Was Just Done" describing what was accomplished
- Update "What's Next" if applicable

**DO NOT:**
- Proceed to other work before updating state.md
- Batch multiple task completions before updating
- Claim a task is complete without documenting it in state.md

### 2. Follow Trello Completion Workflow

When completing tasks with Trello cards:
1. `bpsai-pair ttask done TRELLO-XX --summary "..."`
   - ✓ Checks acceptance criteria
   - ✓ Moves card to Done list
   - ✓ Auto-updates local task file
   - ✓ Runs completion hooks (updates state.md)

**DO NOT** use `task update --status done` for Trello-linked tasks.
The `ttask done` command handles everything automatically.

**Bypasses (audited):**
- `--no-strict`: Skip AC check (logged to bypass_log.jsonl)
- `task update --local-only --reason "..."`: Update local only (logged)

---

## Before Doing Anything

1. **Read** `.paircoder/capabilities.yaml` — understand what you can do
2. **Read** `.paircoder/context/state.md` — understand current status
3. **Check** if a skill applies to the user's request (see `.claude/skills/`)
4. **If starting a task**: Run `bpsai-pair task update TASK-XXX --status in_progress`

---

## ⚠️ BEFORE ANY TRELLO OPERATIONS

**MANDATORY:** Before creating plans, syncing to Trello, or updating cards:

1. **Configure your board** — Run `bpsai-pair trello use-board <board-id>` to set your active board
2. **Set project defaults** — Configure your project name, stack, and repo URL in `.paircoder/config.yaml`
3. **Use valid values** — Only use dropdown values that exist on your Trello board

**NEVER:**
- Create new custom field dropdown values without checking the board first
- Use `maintenance` as plan type (use `chore`)

---


## Task Naming Convention

| Sprint Tasks | Format | Example |
|--------------|--------|---------|
| Current sprint | `T{sprint}.{seq}` | T18.1, T18.2, T19.1 |
| Legacy | `TASK-{num}` | TASK-150 |
| Release | `REL-{sprint}-{seq}` | REL-18-01 |

**Use the format specified in the backlog document.** If backlog says `T18.1`, create task with id `T18.1`, not `TASK-###`.

---

## Valid Plan Types

```
feature  - New functionality
bugfix   - Bug fixes  
refactor - Code improvements
chore    - Maintenance, cleanup, docs, releases
```

**`maintenance` is NOT valid.** Use `chore` instead.

---

## Key Files

| File | Purpose |
|------|---------|
| `.paircoder/capabilities.yaml` | Your capabilities and when to use them |
| `.paircoder/context/project.md` | Project overview and constraints |
| `.paircoder/context/state.md` | Current plan, tasks, and status |
| `.paircoder/context/workflow.md` | How we work here |
| `.paircoder/config.yaml` | Project configuration |

## Your Roles

You can operate in different roles depending on the work:

### Navigator (Planning & Design)
- Clarify goals, ask questions
- Propose approaches with tradeoffs
- Create/update plans and tasks
- Strategic thinking

### Driver (Implementation)
- Write and update code
- Run tests
- Follow task specifications
- Tactical execution

### Reviewer (Quality)
- Review code changes
- Check for issues
- Ensure gates pass
- Suggest improvements

## Skills

Skills in `.claude/skills/` are auto-discovered by Claude Code:

| Skill | Purpose |
|-------|---------|
| `designing-and-implementing` | Feature development workflow |
| `implementing-with-tdd` | Test-driven development |
| `reviewing-code` | Code review workflow |
| `finishing-branches` | Branch completion |
| `managing-task-lifecycle` | Task workflow with Trello |
| `planning-with-trello` | Planning with Trello integration |
| `planning-with-pm` | Planning with provider-agnostic PM |
| `creating-skills` | Skill creation guide |
| `architecting-modules` | Module decomposition and file size management |
| `auditing-sibling-projects` | Cross-repo contract detection and impact analysis |
| `running-qc` | Browser-based QC testing with Divona |

## Skill Triggers

When you see these patterns, use the corresponding skill:

| User Says | Suggested Skill |
|-----------|-----------------|
| "build a...", "create a...", "add a..." | `designing-and-implementing` |
| "fix", "bug", "broken", "error" | `implementing-with-tdd` |
| "review", "check", "look at" | `reviewing-code` |
| "done", "finished", "ready to merge" | `finishing-branches` |

> **Note:** `managing-task-lifecycle`, `planning-with-trello`, `running-qc`,
> and `auditing-sibling-projects` are slash-only after T44.11b (DMI). Invoke
> them via `/start-task`, `/pc-plan`, `/run-qc`, and `/pc-audit-sibling`
> respectively — natural-language triggers will not auto-invoke.

## After Completing Work

**⚠️ This is a NON-NEGOTIABLE requirement. See top of this document.**

1. **Trello** (if card exists): `bpsai-pair ttask done TRELLO-XX --summary "..."`
   - This automatically updates local task file and runs completion hooks
2. **Non-Trello tasks only**: `bpsai-pair task update <id> --status done`
3. **IMMEDIATELY update** `.paircoder/context/state.md`:
   - Mark task as done in task list (✓)
   - Add session entry under "What Was Just Done"
   - Update "What's Next"

**You are NOT done until state.md is updated.**

## Project-Specific Notes

## Slash Commands

Quick commands available via `/command` in Claude Code:

| Command | Purpose |
|---------|---------|
| `/pc-plan` | Enter Navigator role, create plan with budget validation |
| `/start-task <ID>` | Enter Driver role, work on task with verification gates |
| `/draft-backlog` | Generate an engage-compatible backlog from description |
| `/make-it-so` | Intent to shipped PR in one command |
| `/run-qc` | Dispatch QC test suite |
| `/pc-audit-sibling` | Run cross-repo contract audit |
| `/update-skills` | Refresh skills from latest template |

**Usage**: Type `/pc-plan backlog-sprint-28.md` in the chat to run the planning workflow.

**Note**: For project status, use `bpsai-pair status` CLI command (no slash command).

## CLI Reference

```bash
# Status
bpsai-pair status

# Plans
bpsai-pair plan list
bpsai-pair plan show <id>

# Tasks
bpsai-pair task list --plan <id>
# For non-Trello tasks:
bpsai-pair task update <id> --status done
# For Trello-linked tasks - use ttask done instead (handles local update)
# Emergency local-only update (audited):
bpsai-pair task update <id> --status done --local-only --reason "..."

# Skills
bpsai-pair skill list
bpsai-pair skill validate
bpsai-pair skill export --all --format cursor

# Trello Tasks
bpsai-pair ttask start TRELLO-XX           # Budget check runs automatically
bpsai-pair ttask start TRELLO-XX --budget-override  # Override budget (audited)
bpsai-pair ttask done TRELLO-XX --summary "..."     # Complete with AC check
bpsai-pair ttask done TRELLO-XX --no-strict         # Skip AC check (audited)

# Budget
bpsai-pair budget status
bpsai-pair budget check --task <id>

# Context
bpsai-pair context-sync --last "..." --next "..."
bpsai-pair pack
```

---
