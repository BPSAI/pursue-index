# Development Workflow

## Branch Strategy

| Branch Type | Naming | Purpose |
|-------------|--------|---------|
| `main` | — | Stable, release-ready code |
| `feature/*` | `feature/short-description` | New features |
| `fix/*` | `fix/issue-or-description` | Bug fixes |
| `refactor/*` | `refactor/what` | Code improvements |
| `docs/*` | `docs/what` | Documentation only |

## Branch Policy

PairCoder enforces branch discipline to protect main/dev from
accidental source code changes.

**Rules:**

| Change Type | Allowed on main/dev? | Enforcement |
|-------------|---------------------|-------------|
| Source code (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`) | No | BLOCK -- must use a feature branch |
| Documentation (`.md`, `.txt`) | Yes | WARN only |
| Config / state (`.yaml`, `.yml`, `.json`) | Yes | WARN only |

**Configuration:**

Set `workflow.require_feature_branch: true` in `.paircoder/config.yaml`
to enable BLOCK escalation. When disabled (default for `minimal` preset),
all protected-branch commits produce a warning only.

```yaml
workflow:
  require_feature_branch: true   # enabled by default for most presets
```

**Admin bypass:** CNS/orchestrator work that must land directly on
protected branches can use `--force` to bypass the branch check.
These bypasses are logged for audit.

## Development Cycle

### 1. Starting Work

```bash
# Check session status (detects new sessions, shows context)
bpsai-pair session status

# Check token budget before starting
bpsai-pair budget status

# Create feature branch
git checkout -b feature/my-feature main

# Or use PairCoder CLI
bpsai-pair feature my-feature --type feature
```

### 2. Planning (for substantial work)

For features or refactors that take more than ~30 minutes:

1. **Create a plan** in `.paircoder/plans/`
2. **Break into tasks** (2-20 minutes each)
3. **Estimate token budget** for the plan
4. **Follow the Skill**: `designing-and-implementing`

```bash
# Estimate tokens for the plan
bpsai-pair plan estimate <plan-id>

# Check if a task fits in remaining budget
bpsai-pair budget check <task-id>
```

### 3. Implementation

Always Follow TDD where practical:

1. Write failing test
2. Write minimal code to pass
3. Refactor
4. Repeat

Use the `implementing-with-tdd` skill for guidance.

### 4. Verification

Before marking work complete:

```bash
# Run tests
pytest tests/ -v

# Quick test run (stop on first failure)
pytest tests/ -x

# Check types (if configured)
mypy src/

# Lint
ruff check src/
```

### 5. Review

Run skill `reviewing-code`

### 6. Completion

```bash
# Update state
bpsai-pair context-sync --last "Completed X" --next "Ready to merge"
```

# Run `finishing-branches` skill

## Commit Messages

Format: `<type>(<scope>): <description>`

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code change that neither fixes nor adds
- `docs`: Documentation only
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

Examples:
```
feat(planning): add plan parser
fix(cli): handle missing config gracefully
docs(adr): update v2 architecture
refactor(flows): extract common validation
```

## Code Style

- **Python**: Follow PEP 8, use type hints
- **YAML**: 2-space indent, quoted strings for ambiguous values
- **Markdown**: ATX headers (`#`), fenced code blocks

## Testing Requirements

| Change Type | Test Requirement |
|-------------|------------------|
| New feature | Unit tests required |
| Bug fix | Regression test required |
| Refactor | Existing tests must pass |
| Config/docs | No tests required |

## Context Updates

### ⚠️ NON-NEGOTIABLE: Update state.md After EVERY Task Completion

**IMMEDIATELY after completing any task**, update `.paircoder/context/state.md`:

1. Mark the task as done in the task list (add ✓)
2. Add a session entry under "What Was Just Done" describing what was accomplished
3. Update "What's Next" if applicable

**Also update state.md:**
- When starting a new task
- When encountering blockers
- At end of session

**You are NOT done with a task until state.md reflects the completion.**

## Working with AI Agents

When using Claude Code, Codex CLI, or similar:

1. Point them to `.paircoder/capabilities.yaml`
2. Let them read `context/project.md` and `context/state.md`
3. They should suggest appropriate flows based on your request
4. Use `session status` to check context and budget
5. Update state after they complete work

**Token Budget Awareness:**
- `check_token_budget` hook warns before large tasks
- `session status` shows remaining context budget
- Plan tasks to fit within session limits

## Definition of Done

**A task is NOT complete until ALL of these are done:**

- [ ] Code compiles/runs without errors
- [ ] Tests pass (if applicable)
- [ ] Trello card updated (if exists): `ttask done` to check AC and move card
- [ ] Local task file updated: `task update --status done`
- [ ] **state.md updated** with task completion and session notes ← NON-NEGOTIABLE
- [ ] Committed with proper message

**⚠️ Skipping the state.md update is a workflow violation.**
