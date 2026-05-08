---
name: planning-with-pm
description: Manages feature planning workflow with provider-agnostic PM operations. Detects active provider and adapts commands accordingly.
argument-hint: "[backlog-file]"
skills: [planning-with-pm]
agent-roles: [navigator]
---

# Planning with PM (Provider-Agnostic)

> Replaces `planning-with-trello` — works with any PM provider or local-only.

## When to Use

- Planning new features, bugfixes, or refactors
- Creating sprint backlogs
- Breaking work into tasks with estimates
- Syncing plans to any PM provider (Trello, Linear, Jira, etc.)

## Pre-Flight: Detect Provider

```bash
bpsai-pair pm status
```

**Decision tree based on output:**

| Output | Mode | Commands |
|--------|------|----------|
| `Provider: <name> (healthy)` | PM provider | Use `pm` commands |
| `No PM provider configured` + Trello in config | Trello compat | Use `ttask` / `plan sync-trello` |
| `No PM provider configured` + no Trello | Local-only | Skip sync steps |

```bash
# Also check budget
bpsai-pair budget status
```

**Budget Warning**: If above 80% daily usage, warn user before proceeding.

## Planning Workflow

### Step 1: Context Gathering

```bash
bpsai-pair status
cat .paircoder/context/state.md
cat .paircoder/context/project.md
```

### Step 2: Intelligence Integration (Optional)

```bash
bpsai-pair workspace status
bpsai-pair feedback query feature
bpsai-pair feedback status
```

Use intelligence data for:
- Token estimates for complexity scoring
- Model recommendations per task type
- Effort-level validation (S/M/L)
- Cross-repo impact detection

### Step 3: Design the Plan

| Attribute | Format | Example |
|-----------|--------|---------|
| **Slug** | kebab-case | `webhook-support` |
| **Type** | feature \| bugfix \| refactor \| chore | `feature` |
| **Title** | Human-readable | "Add Webhook Support" |

**Valid Plan Types:** `feature`, `bugfix`, `refactor`, `chore`

### Step 4: Task Breakdown

Break work into 3-8 tasks with complexity estimates:

| Complexity | Effort | Description |
|------------|--------|-------------|
| 0-20 | S | Trivial |
| 21-40 | S | Simple |
| 41-60 | M | Moderate |
| 61-80 | L | Complex |
| 81-100 | L | Epic (consider splitting) |

**Task ID Format**: `T<sprint>.<sequence>` (e.g., T28.1, T28.2)

### Step 4.5: Scope Detection

After calculating total complexity from the task breakdown, detect whether the work should be scoped as an **Epic** or a **Story**:

| Condition | Scope | Reason |
|-----------|-------|--------|
| `num_sprint_targets > 1` | Epic | Work spans multiple sprints |
| `total_cx > sprint_budget` | Epic | Exceeds single-sprint capacity |
| Otherwise | Story | Fits within one sprint |

**Default sprint budget:** 300 cx (configurable via `config.yaml` key `token_budget.sprint_cx_budget`).

When total complexity triggers Epic scope, the suggested sprint count is calculated as `ceil(total_cx / sprint_budget)`.

**Note:** `plan new --total-cx <value>` runs this detection automatically via `detect_scope()` in `planning/scope_detector.py`. You do not need to call it manually, but understanding the rules helps when reviewing scope decisions.

### Step 5: Budget Check

```bash
bpsai-pair budget check --estimated-tokens <total_estimate>
```

If budget check fails: reduce scope, split plans, or get explicit user approval.

### Step 6: Create Plan

```bash
bpsai-pair plan new <slug> --type <type> --title "<title>" --total-cx <sum>
```

**Scope auto-detection**: When `--total-cx` is provided, scope is auto-detected (see Step 4.5). To override the auto-detected scope, pass `--scope epic` or `--scope story` explicitly.

**Epic auto-creation**: When a PM provider with `hierarchy` capability is connected, `plan new` automatically creates an Epic in the provider and stores `epic_provider_id` in plan metadata.

### Step 7: Create Task Files

For each task:

1. **Register metadata**:
   ```bash
   bpsai-pair plan add-task <plan-slug> \
       --id "T<sprint>.<seq>" \
       --title "<task title>" \
       --complexity <0-100> \
       --priority <P0|P1|P2|P3>
   ```

2. **Write task content** to `.paircoder/tasks/T<sprint>.<seq>.task.md` with:
   - Objective, Files to Update, Implementation Plan
   - Acceptance Criteria (checkboxes)
   - Verification commands

### Step 8: Sync to Provider

**PM provider mode:**
```bash
# Sync all local tasks to provider
bpsai-pair pm sync
```

**Trello compat mode:**
```bash
bpsai-pair plan sync-trello <plan-id> --dry-run
bpsai-pair plan sync-trello <plan-id>
```

**Local-only mode:** Skip this step.

### Step 9: Custom Fields (PM provider)

```bash
bpsai-pair pm set-field <item-id> --field "Project" --value "PairCoder"
bpsai-pair pm set-field <item-id> --field "Stack" --value "Package"
bpsai-pair pm set-field <item-id> --field "Effort" --value "M"
```

### Step 10: Update State

```bash
bpsai-pair context-sync \
    --last "Created plan: <plan-id>" \
    --next "Ready to start: <first-task-id>"
```

### Step 11: Report Summary

```
**Plan Created**: <plan-id>
**Type**: <type>
**Tasks**: <count> tasks, <total-complexity> complexity points

| ID | Title | Priority | Complexity | Effort |
|----|-------|----------|------------|--------|
| T28.1 | ... | P0 | 35 | S |

**Provider**: <provider-name> synced / local-only
Ready to start? Use `/start-task T28.1`
```

## Sprint Lifecycle

### Start Sprint

```bash
bpsai-pair pm sprint start <plan-id>
```

Marks the plan as in-progress and fires `on_sprint_planned` hook.

### Complete Sprint

```bash
# View summary
bpsai-pair pm sprint complete <plan-id>

# With carry-forward to next sprint
bpsai-pair pm sprint complete <plan-id> --carry-forward <new-plan-id>
```

Evaluates task statuses, produces summary, optionally moves incomplete tasks.

## PM CRUD Commands

All commands require an active PM provider (`pm_basic` feature).

```bash
# Create work items
bpsai-pair pm create --type task --title "New task"
bpsai-pair pm create --type epic --title "New epic"
bpsai-pair pm create --type task --title "Child" --parent EPIC-ID

# Move items between statuses
bpsai-pair pm move <item-id> --status in_progress
bpsai-pair pm move <item-id> --status done

# Add comments
bpsai-pair pm comment <item-id> "Status update: 50% complete"

# Checklist operations
bpsai-pair pm check <item-id> <checklist-item-id>
bpsai-pair pm check <item-id> <checklist-item-id> --uncheck

# Custom fields
bpsai-pair pm set-field <item-id> --field "Project" --value "PairCoder"

# Hierarchy and relationships
bpsai-pair pm children <parent-id>
bpsai-pair pm tree <root-id>
bpsai-pair pm link <parent-id> <child-id>...    # Re-parent items under a new parent
bpsai-pair pm unlink <child-id>                  # Remove parent relationship

# Task lifecycle (via lifecycle manager)
bpsai-pair pm start <item-id>
bpsai-pair pm done <item-id> --summary "Completed feature X"
bpsai-pair pm block <item-id> --reason "Waiting on API"

# Sync and diagnostics
bpsai-pair pm sync
bpsai-pair pm status
bpsai-pair pm diagnostics
bpsai-pair pm config
```

## PairCoder-Specific Defaults

When planning for PairCoder itself:
- **Project**: PairCoder
- **Stack**: Package (CLI) or Worker (background jobs)
- **Repo URL**: https://github.com/BPSAI/paircoder

## Error Handling

| Scenario | Action |
|----------|--------|
| PM provider unhealthy | Fall back to Trello compat or local-only |
| Sync fails | Plan exists locally — retry sync later |
| Budget check fails | Do NOT proceed without user acknowledgment |
| Plan creation fails | Check for duplicate slugs or invalid types |
| Item not found | Verify provider connection, check item ID format |
