---
description: From intent to shipped PR in one command
allowed-tools: Bash(bpsai-pair:*), Read, Write, Edit
argument-hint: <description of what to build>
---

# Make It So

The full chain from intent to execution.

## Input
$ARGUMENTS

## Workflow

1. **Draft backlog**: Use /draft-backlog to create an engage-compatible backlog from the description
2. **Validate**: Run `bpsai-pair engage <backlog> --dry-run` and show the plan
3. **MANDATORY APPROVAL**: Present the dry-run output to the user. Do NOT proceed without explicit "yes" or "approved" from the user. This is a safety gate.
4. **Execute**: ONLY after user approval, run `bpsai-pair engage <backlog>`
5. **Report**: Show the engage result (tasks done/failed, PR URL, review findings)

## Approval Gate (MANDATORY)

You MUST show the dry-run plan and receive explicit user approval before executing.
This gate exists because engage creates branches, writes code, pushes to remote,
and creates PRs. These are irreversible actions that require human authorization.

DO NOT skip this gate under any circumstances. There is no auto-approve mode.
If you are running headless without a human to approve, STOP after the dry-run
and report the plan. Do not execute.

## Error Handling

If /draft-backlog fails: report the error, do not proceed
If dry-run shows parse errors: fix the backlog and retry
If engage fails: report what completed and what failed

## Tool Restrictions

This command does NOT have Agent tool access. It cannot spawn sub-agents.
It uses /draft-backlog (a Skill) and bpsai-pair engage (a Bash command).