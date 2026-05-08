---
name: managing-task-lifecycle
description: Manages task lifecycle transitions including starting, completing, and blocking tasks with enforcement gates and Trello synchronization.
skills: [managing-task-lifecycle]
agent-roles: [driver]
disable-model-invocation: true
---

# Task Lifecycle Management

## When to Use

- Starting work on a task
- Completing a task with verification
- Blocking a task with reason
- Transitioning task status
- Progress updates during work

## Decision Tree: Which Command?

```
Is Trello connected? (check: bpsai-pair trello status)
│
├── YES → Use `ttask` commands (primary)
│   ├── Start:    bpsai-pair ttask start TRELLO-XX
│   ├── Complete: bpsai-pair ttask done TRELLO-XX --summary "..." --list "Deployed/Done"
│   └── Block:    bpsai-pair ttask block TRELLO-XX --reason "..."
│
└── NO → Use `task update` commands
    ├── Start:    bpsai-pair task update TASK-XXX --status in_progress
    ├── Complete: bpsai-pair task update TASK-XXX --status done
    └── Block:    bpsai-pair task update TASK-XXX --status blocked
```

---

## Starting a Task (Driver Role)

### Pre-Flight Checks

Before starting work, verify everything is ready:

```bash
# Check budget for this task
bpsai-pair budget check <task-id>
# Example : bpsai-pair budget check T1.13

# Verify task exists and get details
bpsai-pair task show <task-id>

# Check for blockers (dependencies)
bpsai-pair task list --status blocked
```

**Budget Warning**: If budget check warns, inform user of token estimate and ask to proceed.

**Task Not Found**: Check if it's a Trello ID (TRELLO-XXX) vs local ID (T1.1).

### Start the Task

```bash
# Start locally (triggers hooks)
bpsai-pair task update <task-id> --status in_progress

# If Trello card exists, start there too
bpsai-pair ttask start TRELLO-XX
```

### Read Task Requirements

```bash
cat .paircoder/tasks/*/<task-id>.task.md
# or
bpsai-pair task show <task-id>
```

Identify ALL acceptance criteria - these MUST be completed before marking done.

### Automatic Hooks on Start

When you start via CLI, these fire automatically:
- `start_timer` - Begins time tracking
- `sync_trello` - Moves card to "In Progress"
- `update_state` - Updates state.md current focus
- `check_token_budget` - Warns if task exceeds budget

---

## During Work

### Follow TDD Approach (See also: `implementing-with-tdd` skill for additional workflow requirements.)

1. **Red**: Write failing test for the requirement
2. **Green**: Write minimal code to pass
3. **Refactor**: Clean up while keeping tests green

```bash
# Run tests frequently
pytest tests/ -x --tb=short

# Or for specific test file
pytest tests/test_<module>.py -v
```

### Follow Wheel-and-spoke Approach (See also: `architecting-modules` skill for file size limits and decomposition patterns.)

### Track Progress

Add progress comments without changing status:

```bash
bpsai-pair ttask comment TRELLO-XX "Completed API endpoints, starting tests"
```

Use for:
- Milestone updates
- Noting decisions
- Progress visibility for team

### Check Off Acceptance Criteria

As you complete each criterion:

```bash
bpsai-pair ttask check TRELLO-XX "<acceptance criterion text>"
```

---

## Pre-Completion Verification (ENFORCEMENT GATE)

**CRITICAL**: Before marking task complete, ALL gates must pass.

### Run Tests

```bash
# Full test suite must pass
pytest tests/ --tb=short

# Check coverage if required
pytest tests/ --cov --cov-report=term-missing
```

### Verify Acceptance Criteria

```bash
# Check what's still unchecked on Trello
bpsai-pair ttask show TRELLO-XX
```

If ANY acceptance criteria are unchecked, complete them before proceeding.

### Self-Review Checklist

Before completing, verify:
- [ ] All acceptance criteria addressed
- [ ] Tests pass
- [ ] No obvious bugs or TODOs left
- [ ] Code follows project conventions

---

## Completing a Task

### For Trello Projects (Recommended)

Use `ttask done` with `--strict` flag (enforcement gate):

```bash
bpsai-pair ttask done TRELLO-XX --strict --summary "What was accomplished" --list "Deployed/Done"
```

This single command will:
- ✓ Verify ALL acceptance criteria are checked (strict mode)
- ✓ Move Trello card to "Deployed/Done" list
- ✓ Add completion summary to card
- ✓ Update local task file status
- ✓ Trigger all completion hooks

**If `--strict` fails**: You have unchecked acceptance criteria. Go back and complete them.

**NEVER use `--force`** unless explicitly instructed by user. Forced completions are logged to `.paircoder/history/bypass_log.jsonl`.

### For Non-Trello Projects

```bash
bpsai-pair task update <task-id> --status done
```

### Common Mistakes

| Mistake | Why Wrong | Correct |
|---------|-----------|---------|
| `task update` only on Trello projects | Doesn't check AC | Use `ttask done` |
| Both commands on Trello projects | Duplication | Just `ttask done` |
| `ttask` on non-Trello projects | Won't work | Use `task update` |
| Skipping `--strict` | No enforcement | Always use `--strict` |

---

## Post-Completion (NON-NEGOTIABLE)

### Update State

**You MUST update state.md after completing any task.**

```bash
bpsai-pair context-sync \
    --last "<task-id>: <brief description of what was accomplished>" \
    --next "<next task ID or 'Ready for next task'>"
```

Or manually edit `.paircoder/context/state.md`:
- Add entry under "What Was Just Done"
- Update "What's Next"
- Mark task as done in any task lists

### Report Completion

```
✅ **Task Complete**: <task-id>

**Summary**: <what was accomplished>
**Time**: <actual time if tracked>
**Tests**: All passing
**Acceptance Criteria**: All verified ✓

**Files Changed**:
- path/to/file1.py
- path/to/file2.py

**Next Task**: <next task ID> or "Sprint complete!"
```

### Automatic Hooks on Complete

These fire automatically:
- `stop_timer` - Stops timer, records duration
- `record_metrics` - Records token usage and costs
- `record_velocity` - Tracks sprint velocity
- `sync_trello` - Moves card to "Deployed/Done"
- `update_state` - Updates state.md
- `check_unblocked` - Identifies newly unblocked tasks

---

## Blocking a Task

When a task cannot proceed:

```bash
# With Trello
bpsai-pair ttask block TRELLO-XX --reason "Waiting for API documentation"

# Without Trello
bpsai-pair task update <task-id> --status blocked
```

Hooks fired:
- `sync_trello` - Moves card to "Issues/Tech Debt"
- `update_state` - Updates state.md

---

## Error Recovery

### Tests Fail During Completion
1. Fix the failing tests
2. Re-run verification
3. Then complete

### AC Verification Fails (`--strict` blocks)
1. Check which items unchecked: `bpsai-pair ttask show TRELLO-XX`
2. Complete the missing work
3. Check off items: `bpsai-pair ttask check TRELLO-XX "<item>"`
4. Retry completion

### Force Completion (LAST RESORT)
```bash
# This logs a bypass - only with explicit user approval
bpsai-pair ttask done TRELLO-XX --force --summary "<summary>"
```

Bypasses are logged to `.paircoder/history/bypass_log.jsonl` for audit.

---

## Task ID Formats

| Format | Example | Use For |
|--------|---------|---------|
| Sprint task | T1.1 | `bpsai-pair task` commands |
| Legacy | TASK-150 | `bpsai-pair task` commands |
| Trello | TRELLO-abc123 | `bpsai-pair ttask` commands |

---

## Task Status Values

| Status | Meaning | Trello List |
|--------|---------|-------------|
| `pending` | Not started | Backlog / Planned |
| `in_progress` | Currently working | In Progress |
| `blocked` | Waiting on something | Issues / Blocked |
| `review` | Ready for review | Review |
| `done` | Completed | Deployed / Done |

---

## Task Readiness (on_task_ready Hook)

Tasks automatically transition from Intake/Backlog to Planned/Ready when they meet readiness criteria:

**Readiness Criteria:**
1. Has a title (non-empty)
2. Has a plan assigned (plan_id set)
3. Has acceptance criteria (markdown checklist items: `- [ ]` in body)
4. Status is "pending"

**Triggered By:**
- `plan sync-trello` command (fires `on_task_ready` hooks by default)
- Skip with `--no-fire-ready` flag

**What Happens:**
- `sync_trello` hook moves card from Intake/Backlog to Planned/Ready
- `update_state` hook updates state.md

**Enforcement:**
Tasks without acceptance criteria should NOT be started. Ensure AC exists before beginning work.

---

## Quick Reference

### Starting Work
```bash
bpsai-pair budget check T1.1
bpsai-pair task update T1.1 --status in_progress
cat .paircoder/tasks/*/T1.1.task.md
```

### During Work
```bash
pytest tests/ -x
bpsai-pair ttask comment TRELLO-XX "Progress update"
bpsai-pair ttask check TRELLO-XX "AC item text"
```

### Completing Work
```bash
pytest tests/
bpsai-pair ttask done TRELLO-XX --strict --summary "..." --list "Deployed/Done"
bpsai-pair context-sync --last "T1.1: Done" --next "T1.2"
```

---

## CLI Commands Reference

### Local Task Commands (`task`)

| Action | Command |
|--------|---------|
| Start task | `bpsai-pair task update TASK-XXX --status in_progress` |
| Complete task | `bpsai-pair task update TASK-XXX --status done` |
| Block task | `bpsai-pair task update TASK-XXX --status blocked` |
| Show next task | `bpsai-pair task next` |
| Auto-assign next | `bpsai-pair task auto-next` |
| List all tasks | `bpsai-pair task list` |
| Show task details | `bpsai-pair task show TASK-XXX` |

### Trello Card Commands (`ttask`)

| Action | Command                                                                           |
|--------|-----------------------------------------------------------------------------------|
| List Trello cards | `bpsai-pair ttask list`                                                           |
| Show card details | `bpsai-pair ttask show TRELLO-XX`                                                 |
| Start card | `bpsai-pair ttask start TRELLO-XX`                                                |
| **Complete card** | `bpsai-pair ttask done TRELLO-XX --strict --summary "..." --list "Deployed/Done"` |
| Check AC item | `bpsai-pair ttask check TRELLO-XX "item text"`                                    |
| Add comment | `bpsai-pair ttask comment TRELLO-XX "message"`                                    |
| Block card | `bpsai-pair ttask block TRELLO-XX --reason "why"`                                 |
| Move card | `bpsai-pair ttask move TRELLO-XX "List Name"`                                     |

---

## Enforcement Reminders

- **ALWAYS** use `--strict` for `ttask done` (enforcement gate)
- **NEVER** mark task complete without updating state.md
- **NEVER** use `--force` without explicit user approval
- Forced bypasses are logged for audit
- Checkpoints created automatically on task start (if hooks enabled)
