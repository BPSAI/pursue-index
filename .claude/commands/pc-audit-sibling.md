---
description: Run cross-repo impact analysis and audit sibling projects
allowed-tools: Bash(bpsai-pair:*), Bash(cat:*)
argument-hint: [project-name] or leave blank for full check
---

Enter **Reviewer role** to audit sibling projects for cross-repo impact.

## Pre-Flight (Enforcement)

```bash
bpsai-pair workspace status
```

If no workspace configured, inform the user and exit.

## Execute Workflow

Read and follow `.claude/skills/auditing-sibling-projects/SKILL.md` for the complete workflow.

**Input**: $ARGUMENTS

- If a project name is given: run `bpsai-pair workspace audit <project>`
- If no argument: run `bpsai-pair workspace check-impact`

## Key Constraints

- Must be in a workspace (`.paircoder-workspace.yaml` exists)
- Run from within a project directory, not the workspace root
- Review severity levels before recommending actions
- Create cross-repo tasks for high-severity changes
