---
description: Enter Navigator role to create plan from backlog or description
allowed-tools: Bash(bpsai-pair:*), Bash(cat:*)
argument-hint: [backlog-file.md] or [feature description]
---

Enter Planning Mode and use **Navigator role** for planning. Dispatch `explore` and `planner` agents as necessary.

## Pre-Flight (Enforcement)

```bash
bpsai-pair budget status
bpsai-pair trello status
```

If budget >80%, warn user before proceeding.

## Execute Workflow

If Trello connected:
  → Use `.claude/skills/planning-with-trello/SKILL.md`
Else:
  → Use `.claude/skills/designing-and-implementing/SKILL.md`

**Input**: $ARGUMENTS

## Key Constraints

- Plan types: `feature` | `bugfix` | `refactor` | `chore` (NOT `maintenance`)
- Task IDs: `T<sprint>.<seq>` format (e.g., T1.1)
- Task file content must be written directly - `plan add-task` only accepts metadata
- Always update state.md after planning
- Set your project defaults in `.paircoder/config.yaml`
