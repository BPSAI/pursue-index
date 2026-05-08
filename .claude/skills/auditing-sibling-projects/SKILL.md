---
name: auditing-sibling-projects
description: Runs cross-repo contract detection and impact analysis on sibling projects in a workspace. Detects schema, route, command, and config changes, traces the dependency graph, and produces an impact report with severity and recommended actions.
disable-model-invocation: true
---

# Auditing Sibling Projects

## When to Use

- Before merging changes that affect shared contracts (schemas, routes, configs)
- When a provider repo (e.g., CLI) has changed and consumers (e.g., API) need review
- During sprint planning to assess cross-repo impact
- When the user asks to check impact or audit sibling projects

## Prerequisites

- A workspace must be configured (`.paircoder-workspace.yaml` exists)
- Projects must declare `consumers`/`consumes` relationships
- Must be run from within a project directory inside the workspace

## Workflow

### 1. Load Workspace

```bash
bpsai-pair workspace status
```

Verify workspace is configured and all projects are discovered.

### 2. Check Impact

```bash
# Check contract changes since last commit
bpsai-pair workspace check-impact

# Check since a specific commit
bpsai-pair workspace check-impact --since <commit-hash>

# Machine-readable output
bpsai-pair workspace check-impact --json
```

Review the impact report:
- **Severity**: high (schema/route), medium (command), low (config)
- **Affected repos**: consumers that may need updates
- **Recommended actions**: specific steps for each affected repo

### 3. Audit a Specific Sibling

```bash
# Audit a specific project
bpsai-pair workspace audit <project-name>

# With JSON output
bpsai-pair workspace audit <project-name> --json

# With auto-fix for trivial issues (future)
bpsai-pair workspace audit <project-name> --fix
```

### 4. Review and Act

For each recommended action:
1. Open the affected sibling project
2. Check the specific files mentioned in the impact report
3. Update schemas, routes, or configs as needed
4. Run tests in the sibling project
5. Create cross-repo tasks if changes are needed

### 5. Record Results

The audit is automatically recorded in `.paircoder-audit.jsonl`.

## Severity Guide

| Level | Change Types | Action Required |
|-------|-------------|-----------------|
| High | Schema, Route | Immediate review of all consumers |
| Medium | Command | Review consumer integrations |
| Low | Config | Check config compatibility |

## Example Session

```
> bpsai-pair workspace check-impact --since HEAD~5

Impact Analysis
  Severity: high
  Affected repos: api, website

Recommended Actions:
  - Update api to match new schema from cli
  - Update website API client for route changes in cli

> bpsai-pair workspace audit api

Audit: api
  Severity: high
  Changes: 2

Recommended Actions:
  - Update api to match new schema from cli
```
