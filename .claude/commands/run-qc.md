---
description: Run QC test suites via Chrome extension for interactive regression testing
allowed-tools: Bash(bpsai-pair:*), Bash(python:*), Read, Grep, Glob
argument-hint: [--env dev] [--tags critical] [--suite login-flow]
---

Run QC test suites using the **running-qc** skill.

## Arguments

- `--env <name>` -- Environment profile (default: from config `default_environment`)
- `--tags <tags>` -- Comma-separated tag filter (e.g., `critical,e2e`)
- `--suite <name>` -- Run a specific suite by name

## Pre-Flight

```bash
bpsai-pair qc list $ARGUMENTS
bpsai-pair qc validate
```

## Execute

Follow `.claude/skills/running-qc/SKILL.md` for the complete workflow.

1. Discover and filter suites
2. Load environment config
3. Check preconditions
4. Execute each suite via QC agent (Chrome)
5. Collect and persist results
6. Display summary

```bash
bpsai-pair qc report
```
