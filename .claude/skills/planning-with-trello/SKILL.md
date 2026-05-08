---
name: planning-with-trello
description: Manages feature planning workflow including budget validation, task creation, and Trello synchronization.
skills: [planning-with-trello]
agent-roles: [navigator]
disable-model-invocation: true
---

# Planning with Trello

## When to Use

- Planning new features, bugfixes, or refactors
- Creating sprint backlogs
- Breaking work into tasks with estimates
- Syncing plans to Trello boards

## Pre-Flight Checks

Before planning, verify readiness:

```bash
# Check current budget status
bpsai-pair budget status

# Verify Trello connection
bpsai-pair trello status
```

**Budget Warning**: If above 80% daily usage, warn user before proceeding with planning.

## Input Types

Planning can start from:

1. **Backlog file**: `backlog-sprint-##.md` always located in `.paircoder/context/`
2. **Feature description**: Natural language description of the work

## Planning Workflow

### Step 1: Context Gathering

Read current project state:

```bash
bpsai-pair status
cat .paircoder/context/state.md
cat .paircoder/context/project.md
```

### Step 2: Design the Plan

Determine plan attributes:

| Attribute | Format | Example |
|-----------|--------|---------|
| **Slug** | kebab-case | `webhook-support` |
| **Type** | feature \| bugfix \| refactor \| chore | `feature` |
| **Title** | Human-readable | "Add Webhook Support" |

**Valid Plan Types:**
- `feature` - New functionality
- `bugfix` - Bug fixes
- `refactor` - Code improvements
- `chore` - Maintenance, cleanup, docs, releases

⚠️ **`maintenance` is NOT valid** - use `chore` instead.

### Step 3: Task Breakdown

Break work into 3-8 tasks with complexity estimates:

| Complexity | Time Estimate | Description |
|------------|---------------|-------------|
| 0-20 | < 1 hour | Trivial |
| 21-40 | 1-2 hours | Simple |
| 41-60 | 2-4 hours | Moderate |
| 61-80 | 4-8 hours | Complex |
| 81-100 | 8+ hours | Epic (consider splitting) |

**Task ID Format**: `T<sprint>.<sequence>` (e.g., T1.1, T1.2)

### Step 4: Budget Estimation

Before creating tasks, estimate total token budget:

```bash
bpsai-pair budget check --estimated-tokens <total_estimate>
```

If budget check fails:
- Reduce scope
- Split into multiple plans
- Get explicit user approval before proceeding

### Step 5: Create Plan

```bash
bpsai-pair plan new <slug> --type <type> --title "<title>"
```

### Step 6: Create Task Files

⚠️ **CRITICAL**: The CLI `plan add-task` only accepts metadata. Task file **content** must be written directly.

For each task:

1. **Register task metadata** with CLI:
   ```bash
   bpsai-pair plan add-task <plan-slug> \
       --id "T<sprint>.<seq>" \
       --title "<task title>" \
       --complexity <0-100> \
       --priority <P0|P1|P2|P3>
   ```

2. **Write task content** directly to the file:
   ```bash
   # File: .paircoder/tasks/<plan-slug>/T<sprint>.<seq>.task.md
   ```
   
   The file must contain:
   - **Objective**: What this task accomplishes
   - **Files to Update**: Specific files with expected changes
   - **Implementation Plan**: Step-by-step approach
   - **Acceptance Criteria**: Checkboxes for verification
   - **Verification**: How to confirm completion

**Task File Template:**
```markdown
---
id: T1.1
title: Task title here
status: pending
priority: P1
complexity: 35
plan: plan-slug
---

# Objective

Clear description of what this task accomplishes.

# Files to Update

| File | Change |
|------|--------|
| path/to/file.py | Description of change |

# Implementation Plan

1. First step
2. Second step
3. Third step

# Acceptance Criteria

- [ ] First criterion with measurable outcome
- [ ] Second criterion
- [ ] Tests pass

# Verification

```bash
# Commands to verify completion
pytest tests/test_module.py -v
grep "expected" path/to/file.py
```
```

### Step 7: Sync to Trello

```bash
# Preview sync
bpsai-pair plan sync-trello <plan-id> --dry-run

# Sync to Intake/Backlog (default for new tasks)
bpsai-pair plan sync-trello <plan-id>

# Sync directly to Planned/Ready list
bpsai-pair plan sync-trello <plan-id> --target-list "Planned/Ready"

# Verify sync
bpsai-pair trello status
```

**Task Ready Workflow:**

By default, `sync-trello` fires `on_task_ready` hooks for tasks that meet readiness criteria:
- Has a title
- Has a plan assigned
- Has acceptance criteria (markdown checklist items in body)
- Status is "pending"

The hook automatically moves qualifying tasks from Intake/Backlog to Planned/Ready.

```bash
# Skip the on_task_ready hook
bpsai-pair plan sync-trello <plan-id> --no-fire-ready
```

### Step 8: Update State

```bash
bpsai-pair context-sync \
    --last "Created plan: <plan-id>" \
    --next "Ready to start: <first-task-id>"
```

### Step 9: Report Summary

Provide summary to user:

```
**Plan Created**: <plan-id>
**Type**: <type>
**Tasks**: <count> tasks, <total-complexity> complexity points

| ID | Title | Priority | Complexity | Estimate |
|----|-------|----------|------------|----------|
| T1.1 | ... | P0 | 35 | ~2h |
| T1.2 | ... | P1 | 55 | ~4h |

**Token Budget**: ~<estimate>K tokens (<percent>% of daily limit)
**Trello**: <count> cards created in "Planned/Ready"

Ready to start? Use `/start-task T1.1`
```

## Board Structure

Standard 7-list Trello board:

1. **Intake/Backlog** - New ideas, not selected
2. **Planned/Ready** - Selected for upcoming work
3. **In Progress** - Active development
4. **Review/Testing** - Under review
5. **Deployed/Done** - Completed
6. **Issues/Tech Debt** - Bugs, improvements
7. **Notes/Ops Log** - Decisions, notes

## Card Conventions

### Title Format
```
[Stack] Task Name
```
Examples: `[CLI] Add MCP server`, `[Docs] Update README`

### Required Custom Fields

| Field | When | Values |
|-------|------|--------|
| **Project** | On creation | Your project name |
| **Stack** | On creation | React, Flask, Worker/Function, Infra, Collection |
| **Repo URL** | On creation | GitHub repo URL |
| **Effort** | On creation | S, M, L |

### Effort Sizing

| Size | Time Estimate | Complexity |
|------|---------------|------------|
| S | Few hours | 0-30 |
| M | Half to full day | 31-60 |
| L | Multiple days | 61-100 |

## Error Handling

### Trello sync fails
Plan exists locally - report partial success, retry sync later.

### Budget check fails
DO NOT proceed without explicit user acknowledgment.

### Plan creation fails
Check for duplicate slugs or invalid types.

## CLI Commands Reference

```bash
# Plan management
bpsai-pair plan new <slug> --type <type> --title "<title>"
bpsai-pair plan list
bpsai-pair plan show <id>
bpsai-pair plan status <id>
bpsai-pair plan add-task <id> --id <task-id> --title "<title>" --complexity <n>

# Trello sync
bpsai-pair plan sync-trello <id> --dry-run
bpsai-pair plan sync-trello <id> --target-list "Planned/Ready"
bpsai-pair plan sync-trello <id> --no-fire-ready  # Skip on_task_ready hooks

# Budget
bpsai-pair budget status
bpsai-pair budget check --estimated-tokens <n>

# Context
bpsai-pair context-sync --last "..." --next "..."
```

