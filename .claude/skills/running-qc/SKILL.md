---
name: running-qc
description: Run interactive browser-based QC tests via Chrome extension. Discovers suites, resolves environments, spawns QC agent, collects results.
skills: [running-qc]
agent-roles: [divona]
disable-model-invocation: true
---

# Running QC Tests

## When to Use

- Before merging a branch (regression testing)
- After deploying to staging (smoke testing)
- As part of sprint completion (acceptance testing)
- On-demand via `/run-qc` command

## Prerequisites

1. **Chrome extension**: Must have Claude in Chrome extension installed (v1.0.36+)
2. **Chrome enabled**: Run `claude --chrome` or `/chrome` to enable
3. **Environment running**: Target app must be accessible at configured URL
4. **QC config**: `.paircoder/qc/config.yaml` must exist with environment profiles

## Element Discovery

The QC agent uses the **Element Discovery Protocol** defined in `.claude/agents/divona.md`.
Key points:
- Prefer `find` tool over screenshot-based coordinate estimation
- Use `form_input` for filling form fields
- Fall back to `read_page` then `screenshot` only when `find` fails

## Workflow

### Step 1: Discover Suites

```bash
bpsai-pair qc list
bpsai-pair qc list --tags critical
```

### Step 2: Validate Specs

```bash
bpsai-pair qc validate
```

Fix any validation errors before running.

### Step 3: Select Environment

Choose the target environment:
- `dev` -- localhost, no login required
- `staging` -- staging server, may need login
- `prod` -- production, READ-ONLY mode

### Step 4: Run QC Suites

For each selected suite:

1. **Load suite spec** from `.paircoder/qc/suites/<name>.qc.yaml`
2. **Resolve environment** -- load config, substitute `${VAR}` variables
3. **Check preconditions** -- verify app is accessible
4. **Execute scenarios** -- run each scenario's steps sequentially via Chrome
5. **Collect results** -- build QCRunResult with per-step observations

### Step 5: Report Results

```bash
bpsai-pair qc report
bpsai-pair qc report --json
```

Results are persisted to `.paircoder/qc/reports/` for gate evaluation.

## Environment Restrictions

### Production Mode (`restrictions.read_only: true`)

When running against production:
- **Navigate and verify ONLY** -- no form submissions
- **Skip destructive scenarios** -- honor `skip_tags`
- **No test data creation** -- observe existing state only

### Tag Filtering

Use `--tags` to run only specific suites:
```bash
# Run only critical suites
/run-qc --tags critical

# Run only smoke tests
/run-qc --tags smoke
```

## Integration with Finishing Branches

The `finishing-branches` skill can optionally include a QC step:

1. After code review passes
2. Before creating the PR
3. Run critical QC suites
4. Include results in PR description

## Gate Integration

QC results feed into the `qc_check` enforcement gate:
- `enforcement.qc_gate: block` -- QC failures block completion
- `enforcement.qc_gate: warn` -- QC failures produce warnings
- `enforcement.qc_gate: off` -- QC check skipped

## Troubleshooting

### Chrome not connected
Run `/chrome` to reconnect. Restart Chrome if needed.

### Page doesn't load
Check that the target environment is running and accessible.

### Login required
The Chrome extension shares your browser login state. Log in manually, then retry.

## CLI Reference

```bash
bpsai-pair qc list [--tags TAG] [--json]
bpsai-pair qc validate [--json]
bpsai-pair qc report [--json]
```
