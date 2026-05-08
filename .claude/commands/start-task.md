---
description: Enter Driver role to work on a task with verification gates
allowed-tools: Bash(bpsai-pair:*), Bash(git:*), Bash(pytest:*), Bash(python:*)
argument-hint: <task-id>
---

Enter **Driver role** to complete task with verification.

**Task ID**: $ARGUMENTS

## Pre-Flight (Enforcement)

```bash
bpsai-pair budget check $ARGUMENTS
bpsai-pair task show $ARGUMENTS
```

If budget warns, inform user and ask to proceed.

## Execute Workflow

Read and follow `.claude/skills/managing-task-lifecycle/SKILL.md` for the complete workflow.

## Key Constraints

- **ALWAYS** use `--strict` for `ttask done` (enforcement gate)
- **NEVER** mark complete without updating state.md
- **NEVER** use `--force` without explicit user approval
- All acceptance criteria must be checked before completion
- Tests must pass before completion

## Task ID Formats

- `T1.1` - Sprint task (for `task` commands)
- `TRELLO-abc` - Trello card (for `ttask` commands)
