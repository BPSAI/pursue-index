---
name: designing-and-implementing
description: Use when receiving feature requests, architectural discussions, or multi-step implementation needs that require design before coding.
skills: [designing-and-implementing]
agent-roles: [navigator, driver]
---

# Design → Plan → Implement

## When to Use This Skill

Check if planning is needed:
```bash
bpsai-pair intent should-plan "user's request here"
```

Use this skill for: features, refactors, multistep work.
Skip planning for: typo fixes, small bugs, documentation tweaks.

## Workflow

### 1. Clarify Requirements
- Restate the goal in 1–3 sentences
- Identify affected components
- Ask clarifying questions if ambiguous
- Research existing code patterns

### 2. Propose Approaches
Present 2–3 options with pros/cons and recommend one.

### 3. Create Plan

```bash
bpsai-pair plan new <slug> --type feature --title "Title"
```

### 4. Add Tasks

Resolve the per-task model before writing the file (MR3.2 — single-source
doctrine, calibration-aware):
```bash
bpsai-pair calibration recommend-model --task-type <type> --complexity <n> [--cross-module]
```

Task format in `.paircoder/tasks/`:
```yaml
---
id: TASK-XXX
title: Task title
status: pending
priority: P0  # P0=must, P1=should, P2=nice
complexity: 30  # 10-100 scale
model: claude-sonnet-5  # from `calibration recommend-model` above
---

## Objective
- What this accomplishes.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Tests pass

## Dependencies
- Requires TASK-YYY (if any)
```

### 5. Sync to Trello

```bash
bpsai-pair plan sync-pm <plan-id> --target-list "Planned/Ready"
```
(`sync-trello` is a deprecated alias)

### 6. Implement Each Task

1. `bpsai-pair task update TASK-XXX --status in_progress`
2. Write tests first (see implementing-with-tdd skill)
3. Implement feature
4. Complete via managing-task-lifecycle skill

## Key Files

- Plans: `.paircoder/plans/`
- Tasks: `.paircoder/tasks/`
- State: `.paircoder/context/state.md`
- Project context: `.paircoder/context/project.md`

## Commands

```bash
bpsai-pair plan list              # List plans
bpsai-pair plan show <id>         # Show plan details
bpsai-pair task list --plan <id>  # Tasks in plan
bpsai-pair task next              # Next task to work on
```
