# PairCoder CLI Complete Reference

> Updated: 2026-02-05 | Version: 2.13.0 | 200+ commands

## Contents

- [Command Groups Overview](#command-groups-overview)
- [Core Commands](#core-commands)
- [Preset Commands](#preset-commands)
- [Planning Commands](#planning-commands)
- [Task Commands](#task-commands)
- [Sprint Commands](#sprint-commands)
- [Skills Commands](#skills-commands)
- [Orchestration Commands](#orchestration-commands)
- [Intent Commands](#intent-commands)
- [GitHub Commands](#github-commands)
- [Standup Commands](#standup-commands)
- [Metrics Commands](#metrics-commands)
- [Budget Commands](#budget-commands)
- [Timer Commands](#timer-commands)
- [Benchmark Commands](#benchmark-commands)
- [Cache Commands](#cache-commands)
- [Session Commands](#session-commands)
- [Compaction Commands](#compaction-commands)
- [Security Commands](#security-commands)
- [Migrate Commands](#migrate-commands)
- [Trello Commands](#trello-commands)
- [Trello Task Commands (ttask)](#trello-task-commands-ttask)
- [MCP Commands](#mcp-commands)
- [Audit Commands](#audit-commands)
- [State Commands](#state-commands)
- [Release Commands](#release-commands)
- [Template Commands](#template-commands)
- [Subagent Commands](#subagent-commands)
- [Gaps Commands](#gaps-commands)
- [Config Commands](#config-commands)
- [Containment Commands](#containment-commands)
- [Enforce Commands](#enforce-commands)
- [Arch Commands](#arch-commands)
- [Telemetry Commands](#telemetry-commands)
- [Feedback Commands](#feedback-commands)
- [Workspace Commands (Pro+)](#workspace-commands-pro)
- [Configuration](#configuration)
- [Environment Variables](#environment-variables)
- [Common Workflows](#common-workflows)

---

## Command Groups Overview

| Group | Purpose | Count |
|-------|---------|-------|
| Core | init, feature, pack, status, validate, ci, context-sync, contained-auto | 8 |
| Preset | Project presets | 4 |
| Planning | plan new/list/show/tasks/status/sync-trello/add-task/estimate | 8 |
| Task | Local task file management | 11 |
| Sprint | Sprint lifecycle management | 2 |
| Skills | Skill management and export | 7 |
| Orchestration | Multi-agent orchestration | 6 |
| Intent | Natural language intent detection | 3 |
| GitHub | GitHub PR integration | 7 |
| Standup | Generate standup summaries | 2 |
| Metrics | Token/cost tracking | 9 |
| Budget | Token budget management | 3 |
| Timer | Time tracking | 5 |
| Benchmark | Agent benchmarking | 4 |
| Cache | Context caching | 3 |
| Session | Session management | 2 |
| Compaction | Context compaction recovery | 5 |
| Security | Security scanning | 4 |
| Migrate | Migration commands | 2 |
| Trello | Trello board configuration | 10 |
| ttask | Trello card operations | 7 |
| MCP | MCP server for Claude Desktop | 3 |
| Audit | Workflow bypass auditing | 3 |
| State | Task execution state machine | 5 |
| Release | Release management | 3 |
| Template | Cookiecutter template management | 2 |
| Subagent | Claude Code subagent management | 1 |
| Gaps | Unified gap detection | 4 |
| Config | Configuration validation | 3 |
| Containment | Containment checkpoint management | 3 |
| Enforce | Enforcement gates for hooks | 2 |
| Arch | Architecture enforcement | 2 |
| Upgrade | Version upgrades | 1 |
| Telemetry | Session telemetry collection and export | 3 |
| Feedback | Calibration and estimation feedback loop | 4 |
| Workspace | Multi-project workspace management (Pro+) | 3 |
| License (ext) | Extended license commands | 5 |
| **Total** | | **200+** |

---

## Core Commands

| Command | Description |
|---------|-------------|
| `init [path] [--preset]` | Initialize repo with PairCoder structure |
| `feature <name>` | Create feature branch with context |
| `pack [--lite]` | Package context for AI agents |
| `context-sync` | Update the context loop |
| `status` | Show current context and recent changes |
| `validate` | Check repo structure and consistency |
| `ci` | Run local CI checks (tests + linting) |
| `contained-auto [task] [-y]` | Start contained autonomous session |

### Examples

```bash
# Initialize new project
bpsai-pair init my-project --preset bps

# Create feature branch
bpsai-pair feature add-auth --type feature --primary "Add authentication"

# Package context (lite for Codex 32KB limit)
bpsai-pair pack --lite --out context.tgz

# Check status
bpsai-pair status

# Start contained autonomous session
bpsai-pair contained-auto              # Interactive
bpsai-pair contained-auto T1.4        # With specific task
bpsai-pair contained-auto -y           # Skip confirmation
```

---

## Preset Commands

| Command | Description |
|---------|-------------|
| `preset list` | List available presets |
| `preset show <name>` | Show preset details |
| `preset preview <name>` | Preview generated config |
| `init --preset <name>` | Initialize with preset |

**Available Presets:** python-cli, python-api, react, fullstack, library, minimal, autonomous, bps

### Examples

```bash
bpsai-pair preset list
bpsai-pair preset show bps
bpsai-pair preset preview autonomous
bpsai-pair init my-project --preset bps
```

---

## Planning Commands

| Command | Description |
|---------|-------------|
| `plan new <slug>` | Create a new plan |
| `plan list` | List all plans |
| `plan show <id>` | Show plan details |
| `plan tasks <id>` | List tasks for a plan |
| `plan status [id]` | Show progress with task breakdown |
| `plan sync-trello <id>` | Sync tasks to Trello board |
| `plan add-task <id>` | Add a task to a plan |
| `plan estimate <id>` | Estimate plan token cost |

### Examples

```bash
# Create feature plan
bpsai-pair plan new my-feature --type feature --title "My Feature"

# Show plan with progress
bpsai-pair plan status plan-2025-12-my-feature

# Sync to Trello
bpsai-pair plan sync-trello plan-2025-12-my-feature --dry-run
bpsai-pair plan sync-trello plan-2025-12-my-feature --target-list "Planned/Ready"
```

---

## Task Commands

| Command | Description |
|---------|-------------|
| `task list` | List all tasks |
| `task show <id>` | Show task details |
| `task update <id> --status` | Update task status (fires hooks) |
| `task next` | Get next recommended task |
| `task next --start` | Auto-start next task |
| `task auto-next` | Full auto-assignment with Trello |
| `task archive` | Archive completed tasks |
| `task restore <id>` | Restore from archive |
| `task list-archived` | List archived tasks |
| `task cleanup` | Clean old archives |
| `task changelog-preview` | Preview changelog entry |

### Examples

```bash
# Get and start next task
bpsai-pair task next --start

# Update task status (fires hooks)
bpsai-pair task update TASK-001 --status in_progress
bpsai-pair task update TASK-001 --status done

# Archive completed tasks
bpsai-pair task archive --completed
bpsai-pair task changelog-preview --since 2025-12-01
```

---

## Sprint Commands

| Command | Description |
|---------|-------------|
| `sprint list [--plan]` | List sprints in a plan |
| `sprint complete <sprint-id> [--skip-checklist --reason]` | Complete sprint with checklist verification |

### Examples

```bash
# List sprints in active plan
bpsai-pair sprint list

# List sprints in specific plan
bpsai-pair sprint list --plan plan-2025-12-feature

# Complete sprint with checklist verification
bpsai-pair sprint complete sprint-17

# Skip checklist (requires reason, logged for audit)
bpsai-pair sprint complete sprint-17 --skip-checklist --reason "Hotfix deployment"
```

---

## Skills Commands

| Command | Description |
|---------|-------------|
| `skill list` | List all skills |
| `skill validate [name]` | Validate skill format against spec |
| `skill export <name> [--format --all --dry-run]` | Export to Cursor/Continue/Windsurf/Codex/ChatGPT |
| `skill install <source> [--overwrite --name --personal]` | Install skill from URL/path |
| `skill suggest` | AI-powered skill suggestions |
| `skill gaps` | Detect missing skills from patterns |
| `skill generate <name>` | Generate skill from detected gap |

### Examples

```bash
# List and validate
bpsai-pair skill list
bpsai-pair skill validate
bpsai-pair skill validate designing-and-implementing

# Export to other platforms
bpsai-pair skill export my-skill --format cursor
bpsai-pair skill export --all --format windsurf
bpsai-pair skill export my-skill --format continue --dry-run

# Install from URL or path
bpsai-pair skill install https://example.com/skill.tar.gz
bpsai-pair skill install ./my-skill/

# AI-powered suggestions
bpsai-pair skill suggest
bpsai-pair skill gaps
bpsai-pair skill generate gap-name
```

---

## Orchestration Commands

| Command | Description |
|---------|-------------|
| `orchestrate task <id>` | Route task to best agent |
| `orchestrate analyze <id>` | Analyze task complexity |
| `orchestrate handoff <id>` | Create handoff package |
| `orchestrate auto-run` | Run single task workflow |
| `orchestrate auto-session` | Run autonomous session |
| `orchestrate workflow-status` | Show current workflow state |

### Examples

```bash
# Analyze task complexity
bpsai-pair orchestrate analyze TASK-001

# Create handoff for another agent
bpsai-pair orchestrate handoff TASK-001 \
  --from claude-code --to codex \
  --progress "Completed step 1 and 2"

# Run autonomous session
bpsai-pair orchestrate auto-session --max-tasks 3
```

---

## Intent Commands

| Command                       | Description |
|-------------------------------|-------------|
| `intent detect <text>`        | Detect work intent from text |
| `intent should-plan <text>`   | Check if planning needed |
| `intent suggest-skill <text>` | Suggest appropriate workflow |

### Examples

```bash
bpsai-pair intent detect "fix the login bug"
# Output: bugfix

bpsai-pair intent should-plan "refactor the database layer"
# Output: true

bpsai-pair intent suggest-skill "review the PR"
# Output: reviewing-code
```

---

## GitHub Commands

| Command | Description |
|---------|-------------|
| `github status` | Check GitHub connection |
| `github create` | Create a pull request |
| `github list` | List pull requests |
| `github merge <pr>` | Merge PR and update task |
| `github link <task>` | Link task to PR |
| `github auto-pr` | Auto-create PR from branch |
| `github archive-merged` | Archive tasks for merged PRs |

### Examples

```bash
# Auto-create PR from branch (detects TASK-xxx)
bpsai-pair github auto-pr
bpsai-pair github auto-pr --no-draft

# Archive all tasks for merged PRs
bpsai-pair github archive-merged --all
```

---

## Standup Commands

| Command | Description |
|---------|-------------|
| `standup generate` | Generate daily summary |
| `standup post` | Post summary to Trello |

### Examples

```bash
bpsai-pair standup generate --format slack
bpsai-pair standup generate --since 48  # Last 48 hours
bpsai-pair standup post
```

---

## Metrics Commands

| Command | Description |
|---------|-------------|
| `metrics summary` | Show metrics for time period |
| `metrics task <id>` | Show metrics for a task |
| `metrics breakdown` | Cost breakdown by dimension |
| `metrics budget` | Show budget status |
| `metrics export` | Export metrics to file |
| `metrics velocity` | Show velocity metrics |
| `metrics burndown` | Show burndown chart data |
| `metrics accuracy` | Show estimation accuracy |
| `metrics tokens` | Show token usage |

### Examples

```bash
bpsai-pair metrics summary
bpsai-pair metrics breakdown --by model
bpsai-pair metrics export --format csv --output metrics.csv
```

---

## Budget Commands

| Command | Description |
|---------|-------------|
| `budget estimate` | Estimate task token cost |
| `budget status` | Show current budget usage |
| `budget check` | Check if task fits budget |

### Examples

```bash
bpsai-pair budget status
bpsai-pair budget estimate TASK-001
bpsai-pair budget check --task TASK-001
```

---

## Timer Commands

| Command | Description |
|---------|-------------|
| `timer start <task>` | Start timer for a task |
| `timer stop` | Stop current timer |
| `timer status` | Show current timer |
| `timer show <task>` | Show time entries |
| `timer summary` | Show time summary |

### Examples

```bash
bpsai-pair timer start TASK-001
bpsai-pair timer status
bpsai-pair timer stop
bpsai-pair timer summary --plan plan-2025-12-feature
```

---

## Benchmark Commands

| Command | Description |
|---------|-------------|
| `benchmark run` | Run benchmark suite |
| `benchmark results` | View results |
| `benchmark compare` | Compare agents |
| `benchmark list` | List benchmarks |

### Examples

```bash
bpsai-pair benchmark run --suite default
bpsai-pair benchmark results --latest
bpsai-pair benchmark compare claude-code codex
```

---

## Cache Commands

| Command | Description |
|---------|-------------|
| `cache stats` | Show cache statistics |
| `cache clear` | Clear context cache |
| `cache invalidate <file>` | Invalidate specific file |

### Examples

```bash
bpsai-pair cache stats
bpsai-pair cache clear
bpsai-pair cache invalidate .paircoder/context/state.md
```

---

## Session Commands

| Command | Description |
|---------|-------------|
| `session check` | Check session status (quiet mode for hooks) |
| `session status` | Show detailed session info with budget |

### Examples

```bash
bpsai-pair session check --quiet
bpsai-pair session status
```

---

## Compaction Commands

| Command | Description |
|---------|-------------|
| `compaction snapshot save` | Save context snapshot |
| `compaction snapshot list` | List snapshots |
| `compaction check` | Check for compaction events |
| `compaction recover` | Recover from compaction |
| `compaction cleanup` | Clean old snapshots |

### Examples

```bash
bpsai-pair compaction snapshot save --trigger "manual"
bpsai-pair compaction snapshot list
bpsai-pair compaction check
bpsai-pair compaction recover
bpsai-pair compaction cleanup --older-than 7
```

---

## Security Commands

| Command | Description |
|---------|-------------|
| `security scan-secrets` | Scan for leaked secrets |
| `security pre-commit` | Run pre-commit checks |
| `security install-hook` | Install git hooks |
| `security scan-deps` | Scan dependency vulnerabilities |

### Examples

```bash
bpsai-pair security scan-secrets --staged
bpsai-pair security scan-deps
bpsai-pair security install-hook
```

---

## Migrate Commands

| Command | Description |
|---------|-------------|
| `migrate` | Run pending migrations |
| `migrate status` | Show migration status |

### Examples

```bash
bpsai-pair migrate status
bpsai-pair migrate
```

---

## Trello Commands

| Command | Description |
|---------|-------------|
| `trello connect` | Connect to Trello |
| `trello status` | Check connection |
| `trello disconnect` | Remove credentials |
| `trello boards` | List available boards |
| `trello use-board <id>` | Set active board |
| `trello lists` | Show board lists |
| `trello config` | View/modify config |
| `trello progress <task>` | Post progress comment |
| `trello webhook serve` | Start webhook server |
| `trello webhook status` | Check webhook status |

### Examples

```bash
bpsai-pair trello connect
bpsai-pair trello boards
bpsai-pair trello use-board 694176ebf4b9d27c6e7a0e73
bpsai-pair trello status
bpsai-pair trello progress TASK-001 --completed "Feature done"
```

---

## Trello Task Commands (ttask)

| Command | Description |
|---------|-------------|
| `ttask list` | List tasks from board |
| `ttask show <id>` | Show task details |
| `ttask start <id> [--budget-override]` | Start working on task (checks budget) |
| `ttask done <id> --summary [--no-strict]` | Complete task (strict AC check by default) |
| `ttask block <id> --reason` | Mark as blocked |
| `ttask comment <id>` | Add comment |
| `ttask move <id>` | Move to different list |

### Examples

```bash
# List and show
bpsai-pair ttask list
bpsai-pair ttask list --list "In Progress"
bpsai-pair ttask show TRELLO-abc123

# Lifecycle
bpsai-pair ttask start TRELLO-abc123
bpsai-pair ttask start TRELLO-abc123 --budget-override  # Override budget warning (logged)
bpsai-pair ttask done TRELLO-abc123 --summary "Implemented feature" --list "Deployed/Done"
bpsai-pair ttask done TRELLO-abc123 --summary "Done" --no-strict  # Skip AC check (logged)
bpsai-pair ttask block TRELLO-abc123 --reason "Waiting for API"

# Comments
bpsai-pair ttask comment TRELLO-abc123 "50% complete"
```

### When to Use `task` vs `ttask`

| Scenario | Command |
|----------|---------|
| Working with local task files | `task` |
| Need hooks to fire (timer, state.md) | `task update` |
| Working directly with Trello cards | `ttask` |
| Adding progress comments to cards | `ttask comment` |
| Card doesn't have local task file | `ttask` |
| Card has linked local task | Either works |

**Recommended workflow:**
- Use `task update` for status changes (fires all hooks)
- Use `ttask comment` for progress notes
- Use `ttask` commands when Trello is your only source

---

## MCP Commands

| Command | Description |
|---------|-------------|
| `mcp serve` | Start MCP server (stdio transport) |
| `mcp tools` | List available tools |
| `mcp test <tool>` | Test tool locally |

### Examples

```bash
bpsai-pair mcp serve
bpsai-pair mcp tools
bpsai-pair mcp test paircoder_task_list
```

### Available MCP Tools (13)

| Tool | Description |
|------|-------------|
| `paircoder_task_list` | List tasks with filters |
| `paircoder_task_next` | Get next recommended task |
| `paircoder_task_start` | Start a task |
| `paircoder_task_complete` | Complete a task |
| `paircoder_context_read` | Read project context |
| `paircoder_plan_status` | Get plan progress |
| `paircoder_plan_list` | List available plans |
| `paircoder_orchestrate_analyze` | Analyze task complexity |
| `paircoder_orchestrate_handoff` | Create handoff package |
| `paircoder_metrics_record` | Record token usage |
| `paircoder_metrics_summary` | Get metrics summary |
| `paircoder_trello_sync_plan` | Sync plan to Trello |
| `paircoder_trello_update_card` | Update Trello card |

---

## Audit Commands

| Command | Description |
|---------|-------------|
| `audit bypasses` | Show recent workflow bypasses |
| `audit summary` | Show bypass summary by type and command |
| `audit clear` | Clear bypass log (dev/testing only) |

### Examples

```bash
# View recent bypasses (default: last 7 days)
bpsai-pair audit bypasses
bpsai-pair audit bypasses --days 30

# Filter by bypass type
bpsai-pair audit bypasses --type budget_override
bpsai-pair audit bypasses --type no_strict
bpsai-pair audit bypasses --type local_only

# Export as JSON
bpsai-pair audit bypasses --json

# View summary breakdown
bpsai-pair audit summary
bpsai-pair audit summary --days 14
```

---

## State Commands

| Command | Description |
|---------|-------------|
| `state show <task>` | Show current execution state and valid transitions |
| `state list` | List all tracked task states |
| `state history [task]` | View state transition history |
| `state reset <task>` | Reset task to NOT_STARTED state |
| `state advance <task> <state>` | Manually advance task to a new state |

### Examples

```bash
# Show task state and valid transitions
bpsai-pair state show T1.1

# List all tracked states
bpsai-pair state list
bpsai-pair state list --status in_progress

# View transition history
bpsai-pair state history
bpsai-pair state history T1.1
bpsai-pair state history --limit 50

# Reset a task (e.g., to redo it)
bpsai-pair state reset T1.1
bpsai-pair state reset T1.1 --yes  # Skip confirmation

# Manually advance state (only valid transitions allowed)
bpsai-pair state advance T1.1 budget_checked
bpsai-pair state advance T1.1 in_progress --reason "Starting work"
```

---

## Release Commands

| Command | Description |
|---------|-------------|
| `release plan` | Generate release preparation tasks |
| `release checklist` | Show the release preparation checklist |
| `release prep` | Verify release readiness and generate tasks for missing items |

### Examples

```bash
bpsai-pair release checklist
bpsai-pair release prep --version 2.9.4
bpsai-pair release plan --version 2.9.4
```

---

## Template Commands

| Command | Description |
|---------|-------------|
| `template check` | Check for drift between source files and cookiecutter template |
| `template list` | List files tracked for template sync |

### Examples

```bash
bpsai-pair template list
bpsai-pair template check
bpsai-pair template check --fix  # Auto-sync drifted files
```

---

## Subagent Commands

| Command | Description |
|---------|-------------|
| `subagent gaps` | List detected subagent gaps from session history |

### Examples

```bash
bpsai-pair subagent gaps
```

---

## Gaps Commands

| Command | Description |
|---------|-------------|
| `gaps detect` | Detect and classify all gaps from session history |
| `gaps list` | List all classified gaps |
| `gaps show <id>` | Show detailed classification for a specific gap |
| `gaps check <id>` | Check quality gates for a specific gap |

### Examples

```bash
bpsai-pair gaps detect
bpsai-pair gaps list
bpsai-pair gaps show GAP-001
bpsai-pair gaps check GAP-001
```

---

## Config Commands

| Command | Description |
|---------|-------------|
| `config validate` | Validate config against preset template |
| `config update` | Update config with missing sections from preset |
| `config show [section]` | Show current config or a specific section |

### Examples

```bash
bpsai-pair config validate
bpsai-pair config show
bpsai-pair config show enforcement
bpsai-pair config update --preset bps
```

---

## Containment Commands

| Command | Description |
|---------|-------------|
| `containment rollback` | Rollback to a containment checkpoint |
| `containment list` | List containment checkpoints |
| `containment cleanup` | Remove old containment checkpoints |

### Examples

```bash
bpsai-pair containment list
bpsai-pair containment rollback checkpoint-2026-01-21
bpsai-pair containment cleanup --older-than 7
```

---

## Enforce Commands

| Command | Description |
|---------|-------------|
| `enforce task-edit` | Enforce task edit rules for PreToolUse hook |
| `enforce state-edit` | Enforce state.md edit rules for PreToolUse hook |

### Examples

```bash
# These are typically called by Claude Code hooks, not manually
bpsai-pair enforce task-edit --file .paircoder/tasks/T1.1.task.md
bpsai-pair enforce state-edit --file .paircoder/context/state.md
```

---

## Arch Commands

| Command | Description |
|---------|-------------|
| `arch check [paths]` | Check architecture constraints |
| `arch suggest-split <file>` | Suggest how to split a large file into smaller modules |

### Examples

```bash
# Check specific files
bpsai-pair arch check src/services/task.py

# Check all modified files
bpsai-pair arch check

# Get split suggestions for large files
bpsai-pair arch suggest-split src/services/large_module.py
```

---

## Configuration

### Config File Location

`.paircoder/config.yaml`

### Key Settings

```yaml
version: "2.8"

project:
  name: "my-project"
  description: "Project description"
  primary_goal: "Main objective"
  coverage_target: 80

models:
  navigator: claude-opus-4-5
  driver: claude-sonnet-4-5
  reviewer: claude-sonnet-4-5

routing:
  by_complexity:
    trivial:   { max_score: 20,  model: claude-haiku-4-5 }
    simple:    { max_score: 40,  model: claude-haiku-4-5 }
    moderate:  { max_score: 60,  model: claude-sonnet-4-5 }
    complex:   { max_score: 80,  model: claude-opus-4-5 }
    epic:      { max_score: 100, model: claude-opus-4-5 }

token_budget:
  warning_threshold: 75
  critical_threshold: 90

hooks:
  enabled: true
  on_task_start:
    - check_token_budget
    - start_timer
    - sync_trello
    - update_state
  on_task_complete:
    - stop_timer
    - record_metrics
    - sync_trello
    - update_state
    - check_unblocked
  on_task_block:
    - sync_trello
    - update_state

trello:
  enabled: true
  board_id: "your-board-id"

enforcement:
  state_machine: false          # Enable formal task state transitions
  strict_ac_verification: true  # Require AC items checked before completion
  require_budget_check: true    # Check budget before starting tasks
  block_no_hooks: true          # Block --no-hooks in strict mode
```

### Enforcement Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `state_machine` | `false` | Enable formal state transitions for tasks |
| `strict_ac_verification` | `true` | Require all AC items checked before `ttask done` |
| `require_budget_check` | `true` | Run budget check before starting tasks |
| `block_no_hooks` | `true` | Block --no-hooks flag in strict mode |

Bypasses (`--no-strict`, `--budget-override`, `--local-only`) are logged to `.paircoder/history/bypass_log.jsonl`.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TRELLO_API_KEY` | Trello API key |
| `TRELLO_TOKEN` | Trello OAuth token |
| `GITHUB_TOKEN` | GitHub personal access token |
| `TOGGL_API_TOKEN` | Toggl time tracking token |
| `PAIRCODER_CONFIG` | Override config file path |

---

## Common Workflows

### Start of Day

```bash
bpsai-pair status           # Check current state
bpsai-pair task list        # See pending tasks
bpsai-pair task next        # Find what to work on
bpsai-pair task update TASK-XXX --status in_progress
```

### During Work (Progress Updates)

```bash
bpsai-pair ttask comment TASK-XXX "Completed API, starting tests"
```

### End of Task

```bash
pytest -v                   # Run tests
git add -A
git commit -m "feat: TASK-XXX - description"
bpsai-pair task update TASK-XXX --status done
bpsai-pair task next        # See what's next
```

### End of Day

```bash
bpsai-pair standup generate # Generate summary
git push                    # Push changes
```

### Sprint Planning

```bash
bpsai-pair plan new sprint-15 --type feature --title "Security & Sandboxing"
# Add tasks to plan...
bpsai-pair plan sync-trello plan-2025-12-sprint-15-security
bpsai-pair trello status    # Verify cards created
```

### Working Directly with Trello

```bash
bpsai-pair ttask list --agent             # Show AI-assigned cards
bpsai-pair ttask start TRELLO-abc123      # Start card
# ... do work ...
bpsai-pair ttask done TRELLO-abc123 --summary "Feature complete" --list "Deployed/Done"
```

### Exporting Skills

```bash
# Export to Cursor
bpsai-pair skill export --all --format cursor

# Export to Windsurf
bpsai-pair skill export my-skill --format windsurf

# Preview export
bpsai-pair skill export my-skill --format continue --dry-run
```

---

## Telemetry Commands

| Command | Description |
|---------|-------------|
| `telemetry status` | Show telemetry collection status and privacy level |
| `telemetry config` | Configure telemetry privacy and retention settings |
| `telemetry export [--format json\|jsonl\|csv] [--anonymize] [--since DATE] [--until DATE]` | Export telemetry data |

---

## Feedback Commands

| Command | Description |
|---------|-------------|
| `feedback status` | Show calibration health, per-type estimates, anomalies |
| `feedback accuracy [--period DAYS]` | Show estimated vs actual performance metrics |
| `feedback calibrate` | Trigger recalibration from telemetry data |
| `feedback query <type> [--json]` | Get token/duration/effort/model estimates for a task type |

---

## Workspace Commands (Pro+)

| Command | Description |
|---------|-------------|
| `workspace init [--name NAME] [--projects name:path,...] [--scan] [--force] [--json]` | Initialize workspace config |
| `workspace status [--json]` | Show workspace config, project states, agent teams |
| `workspace pull [project] [--rebase] [--json]` | Pull latest for workspace projects |
