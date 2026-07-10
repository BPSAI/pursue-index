# PairCoder CLI Complete Reference

> **This file is generated. Do not edit by hand.**
> Regenerate with: `python tools/cli/scripts/generate_cli_reference.py`
> Source of truth: the installed `bpsai-pair` Typer app (`bpsai_pair.cli:app`)
> bpsai-pair 2.30.0 | 266 commands across 47 groups

---

## Contents

- [Top-Level Commands](#top-level-commands)
- [Arch Commands](#arch-commands)
- [Audit Commands](#audit-commands)
- [Benchmark Commands](#benchmark-commands)
- [Budget Commands](#budget-commands)
- [Cache Commands](#cache-commands)
- [Calibration Commands](#calibration-commands)
- [Compaction Commands](#compaction-commands)
- [Config Commands](#config-commands)
- [Containment Commands](#containment-commands)
- [Enforce Commands](#enforce-commands)
- [Feedback Commands](#feedback-commands)
- [Fleet Commands](#fleet-commands)
- [Gaps Commands](#gaps-commands)
- [Github Commands](#github-commands)
- [Intent Commands](#intent-commands)
- [License Commands](#license-commands)
- [MCP Commands](#mcp-commands)
- [Metrics Commands](#metrics-commands)
- [Migrate Commands](#migrate-commands)
- [Orchestrate Commands](#orchestrate-commands)
- [Plan Commands](#plan-commands)
- [PM Commands](#pm-commands)
- [Preset Commands](#preset-commands)
- [QA Commands](#qa-commands)
- [QC Commands](#qc-commands)
- [Query Commands](#query-commands)
- [Release Commands](#release-commands)
- [Review Commands](#review-commands)
- [Security Commands](#security-commands)
- [Session Commands](#session-commands)
- [Setup Commands](#setup-commands)
- [Skill Commands](#skill-commands)
- [Sprint Commands](#sprint-commands)
- [Standup Commands](#standup-commands)
- [State Commands](#state-commands)
- [Subagent Commands](#subagent-commands)
- [Subscription Commands](#subscription-commands)
- [Support Commands](#support-commands)
- [System Commands](#system-commands)
- [Task Commands](#task-commands)
- [Telemetry Commands](#telemetry-commands)
- [Template Commands](#template-commands)
- [Timer Commands](#timer-commands)
- [Trello Commands](#trello-commands)
- [Ttask Commands](#ttask-commands)
- [Workspace Commands](#workspace-commands)

---

## Command Groups Overview

| Group | Commands |
|-------|----------|
| Top-Level | 15 |
| Arch | 7 |
| Audit | 3 |
| Benchmark | 6 |
| Budget | 4 |
| Cache | 3 |
| Calibration | 2 |
| Compaction | 5 |
| Config | 6 |
| Containment | 4 |
| Enforce | 3 |
| Feedback | 4 |
| Fleet | 2 |
| Gaps | 4 |
| Github | 8 |
| Intent | 3 |
| License | 10 |
| MCP | 3 |
| Metrics | 9 |
| Migrate | 1 |
| Orchestrate | 8 |
| Plan | 10 |
| PM | 19 |
| Preset | 3 |
| QA | 4 |
| QC | 4 |
| Query | 6 |
| Release | 6 |
| Review | 5 |
| Security | 4 |
| Session | 3 |
| Setup | 1 |
| Skill | 9 |
| Sprint | 2 |
| Standup | 2 |
| State | 6 |
| Subagent | 1 |
| Subscription | 2 |
| Support | 4 |
| System | 1 |
| Task | 13 |
| Telemetry | 8 |
| Template | 2 |
| Timer | 5 |
| Trello | 18 |
| Ttask | 9 |
| Workspace | 9 |
| **Total** | **266** |

---

## Top-Level Commands

| Command | Description | Options |
|---------|-------------|---------|
| `ci --json` | Run local CI checks (cross-platform). | `--json` |
| `contained-auto [task] --skip-checkpoint --yes --channels` | Start a contained autonomous session. | `--skip-checkpoint`, `--yes`, `--channels` |
| `context-sync --overall --last --next --blockers --json --auto --quiet` | Update the Context Loop in /context/state.md. | `--overall`, `--last`, `--next`, `--blockers`, `--json`, `--auto`, `--quiet` |
| `doctor --json --fix` | Run holistic health check on your PairCoder environment. | `--json`, `--fix` |
| `engage [backlog] --sprint --dry-run --json --max-parallel --skip-planning --resume --resume-run --create-branch --branch --preserve-failed-branch --provider --strict-targets` | Parse a backlog and autonomously execute the sprint. | `--sprint`, `--dry-run`, `--json`, `--max-parallel`, `--skip-planning`, `--resume`, `--resume-run`, `--create-branch`, `--branch`, `--preserve-failed-branch`, `--provider`, `--strict-targets` |
| `feature <name> --primary --phase --force --type` | Create feature branch and scaffold context (cross-platform). | `--primary`, `--phase`, `--force`, `--type` |
| `init [template] --interactive --preset --name --goal` | Initialize repo with governance, context, prompts, scripts, and workflows. | `--interactive`, `--preset`, `--name`, `--goal` |
| `pack --out --extra --dry-run --list --lite --json` | Create agent context package (cross-platform). | `--out`, `--extra`, `--dry-run`, `--list`, `--lite`, `--json` |
| `preflight [path] --quick --verbose` | Run tests with CI-matching environment. | `--quick`, `--verbose` |
| `prime-learn [insight] --no-push --category --yes --reject` | Capture an insight, synthesize it, and append to prime-knowledge YAML. | `--no-push`, `--category`, `--yes`, `--reject` |
| `scan-deps [path] --fail-on --verbose --json --no-cache` | Scan dependencies for vulnerabilities (shortcut for 'security scan-deps'). | `--fail-on`, `--verbose`, `--json`, `--no-cache` |
| `scan-secrets [path] --staged --diff --verbose --json` | Scan for secrets and credentials (shortcut for 'security scan-secrets'). | `--staged`, `--diff`, `--verbose`, `--json` |
| `status --json` | Show current context loop status and recent changes. | `--json` |
| `sweep --since --staged --working --json --category --confidence --fix --deep` | Sweep for dead code in recent changes. | `--since`, `--staged`, `--working`, `--json`, `--category`, `--confidence`, `--fix`, `--deep` |
| `validate --fix --json` | Validate repo structure and context consistency. | `--fix`, `--json` |

---

## Arch Commands

| Command | Description | Options |
|---------|-------------|---------|
| `arch check [path] --staged --fix --strict` | Check architecture constraints. | `--staged`, `--fix`, `--strict` |
| `arch check-encoding [path] --strict` | Flag text-mode file I/O that omits an explicit ``encoding=`` (#373). | `--strict` |
| `arch check-model-ids [path] --strict` | Flag hardcoded ``claude-*`` model-id literals outside the registry (RE.6). | `--strict` |
| `arch check-subprocess [path] --strict` | Flag raw subprocess.run/Popen/etc. | `--strict` |
| `arch check-wiring [path] --strict --generate-baseline` | Flag public symbols/modules written but never wired in (#384). | `--strict`, `--generate-baseline` |
| `arch headroom [path] --threshold --strict` | Report files APPROACHING their architecture caps (#416). | `--threshold`, `--strict` |
| `arch suggest-split <file_path>` | Suggest how to split a large file into smaller modules. |  |

---

## Audit Commands

| Command | Description | Options |
|---------|-------------|---------|
| `audit bypasses --days --limit --type --json` | Show recent workflow bypasses. | `--days`, `--limit`, `--type`, `--json` |
| `audit clear --yes` | Clear bypass log (for development/testing only). | `--yes` |
| `audit summary --days` | Show bypass summary by type and command. | `--days` |

---

## Benchmark Commands

| Command | Description | Options |
|---------|-------------|---------|
| `benchmark compare --baseline --challenger --id` | Compare two agents. | `--baseline`, `--challenger`, `--id` |
| `benchmark list` | List available benchmarks. |  |
| `benchmark matrix-run --include-paid --results-dir --ollama-model --auto-seed --json` | Run the bpsai-framework benchmark matrix via subprocess. | `--include-paid`, `--results-dir`, `--ollama-model`, `--auto-seed`, `--json` |
| `benchmark results --id --latest --json` | View benchmark results. | `--id`, `--latest`, `--json` |
| `benchmark run --only --agents --iterations --dry-run` | Run benchmarks. | `--only`, `--agents`, `--iterations`, `--dry-run` |
| `benchmark seed <path> --run-id --json` | Seed local calibration from a PC2.2 benchmark matrix. | `--run-id`, `--json` |

---

## Budget Commands

| Command | Description | Options |
|---------|-------------|---------|
| `budget check <task_id> --threshold --model --json` | Pre-flight budget check for a task. | `--threshold`, `--model`, `--json` |
| `budget estimate [task_id] --file --model --json` | Estimate token usage for a task or files. | `--file`, `--model`, `--json` |
| `budget programmatic --by --json` | Report month-to-date programmatic API spend vs. | `--by`, `--json` |
| `budget status --model --json` | Show current session budget status. | `--model`, `--json` |

---

## Cache Commands

| Command | Description | Options |
|---------|-------------|---------|
| `cache clear --confirm` | Clear the context cache. | `--confirm` |
| `cache invalidate <file_path>` | Invalidate cache for a specific file. |  |
| `cache stats --json` | Show cache statistics. | `--json` |

---

## Calibration Commands

| Command | Description | Options |
|---------|-------------|---------|
| `calibration recommend-model --task-type --complexity --cross-module --json` | Recommend a plan-time ``model:`` for a task (MR3.2). | `--task-type`, `--complexity`, `--cross-module`, `--json` |
| `calibration report --json` | Recompute calibration and report per task_type x model stats + drift. | `--json` |

---

## Compaction Commands

| Command | Description | Options |
|---------|-------------|---------|
| `compaction check` | Check if compaction recently occurred. |  |
| `compaction cleanup --keep` | Remove old compaction snapshots. | `--keep` |
| `compaction recover` | Recover context after compaction. |  |
| `compaction snapshot list` | List available compaction snapshots. |  |
| `compaction snapshot save --trigger --reason --quiet` | Save a compaction snapshot with current context. | `--trigger`, `--reason`, `--quiet` |

---

## Config Commands

| Command | Description | Options |
|---------|-------------|---------|
| `config prefs get <key>` | Get a user preference value. |  |
| `config prefs list` | List all user preferences. |  |
| `config prefs set <key> <value>` | Set a user preference. |  |
| `config show [section]` | Show current config or a specific section. |  |
| `config update --preset --dry-run` | Update config with missing sections from preset. | `--preset`, `--dry-run` |
| `config validate --preset --json` | Validate config against preset template. | `--preset`, `--json` |

---

## Containment Commands

| Command | Description | Options |
|---------|-------------|---------|
| `containment cleanup --keep` | Remove old containment checkpoints. | `--keep` |
| `containment list` | List containment checkpoints. |  |
| `containment rollback [checkpoint] --dry-run --force --pop-stash` | Rollback to a containment checkpoint. | `--dry-run`, `--force`, `--pop-stash` |
| `containment status --json` | Show containment configuration and active session status. | `--json` |

---

## Enforce Commands

| Command | Description | Options |
|---------|-------------|---------|
| `enforce containment --file --operation` | Enforce containment tiers for PreToolUse hook. | `--file`, `--operation` |
| `enforce state-edit --file --new-content` | Enforce state.md edit rules for PreToolUse hook. | `--file`, `--new-content` |
| `enforce task-edit --file --new-content --old-content` | Enforce task edit rules for PreToolUse hook. | `--file`, `--new-content`, `--old-content` |

---

## Feedback Commands

| Command | Description | Options |
|---------|-------------|---------|
| `feedback accuracy --days --json` | Compare estimated vs actual performance. | `--days`, `--json` |
| `feedback calibrate --json` | Trigger recalibration from telemetry data. | `--json` |
| `feedback query <task_type> --json` | Get estimates for a specific task type. | `--json` |
| `feedback status --json` | Show calibration health and statistics. | `--json` |

---

## Fleet Commands

| Command | Description | Options |
|---------|-------------|---------|
| `fleet audit --branches --issues --json` | Report merged-residue branches and unclosed-but-referenced issues across every workspace repo... | `--branches`, `--issues`, `--json` |
| `fleet check --upgrade --commit --json` | Check bpsai-pair version compliance across workspace repos. | `--upgrade`, `--commit`, `--json` |

---

## Gaps Commands

| Command | Description | Options |
|---------|-------------|---------|
| `gaps check <gap_id> --json` | Check quality gates for a specific gap. | `--json` |
| `gaps detect --json --analyze --with-gates` | Detect and classify all gaps from session history. | `--json`, `--analyze`, `--with-gates` |
| `gaps list --type --json` | List all classified gaps. | `--type`, `--json` |
| `gaps show <gap_id>` | Show detailed classification for a specific gap. |  |

---

## Github Commands

| Command | Description | Options |
|---------|-------------|---------|
| `github archive-merged [pr_number] --all --limit` | Archive tasks whose PRs have been merged. | `--all`, `--limit` |
| `github auto-pr --draft` | Auto-create PR for current branch if it has a task ID. | `--draft` |
| `github create --task --summary --draft --base` | Create a PR for a task. | `--task`, `--summary`, `--draft`, `--base` |
| `github link <task_id> --pr` | Link a task to a PR (update PR title). | `--pr` |
| `github list --state --task-only --json` | List pull requests. | `--state`, `--task-only`, `--json` |
| `github merge <pr_number> --method --no-delete --auto-next` | Merge a PR and optionally assign next task. | `--method`, `--no-delete`, `--auto-next` |
| `github pr [pr_number] --json` | Show PR status for current branch or specific PR. | `--json` |
| `github status --json` | Check GitHub connection status. | `--json` |

---

## Intent Commands

| Command | Description | Options |
|---------|-------------|---------|
| `intent detect <text> --json` | Detect work intent from text. | `--json` |
| `intent should-plan <text> --json` | Check if text should trigger planning mode. | `--json` |
| `intent suggest-flow <text>` | Suggest appropriate flow for text. |  |

---

## License Commands

| Command | Description | Options |
|---------|-------------|---------|
| `license activate --name --json` | Activate this machine on your license. | `--name`, `--json` |
| `license clear-cache --json` | Clear cached license validation data. | `--json` |
| `license deactivate --machine-id --yes --json` | Deactivate a machine from your license. | `--machine-id`, `--yes`, `--json` |
| `license features --json` | List available features for current tier. | `--json` |
| `license install <license_file> --force --activate --no-activate` | Install a license file to ~/.paircoder/license.json. | `--force`, `--activate`, `--no-activate` |
| `license machine-id --full --json` | Display this machine's unique identifier. | `--full`, `--json` |
| `license machines --json --full` | List all machines activated on your license. | `--json`, `--full` |
| `license path --json` | Show license file location. | `--json` |
| `license status --json` | Show current license status. | `--json` |
| `license verify-key --api-url --json` | Verify CLI public key matches API's keypair. | `--api-url`, `--json` |

---

## MCP Commands

| Command | Description | Options |
|---------|-------------|---------|
| `mcp serve --transport --port --verbose` | Start MCP server for Claude and other MCP-compatible agents. | `--transport`, `--port`, `--verbose` |
| `mcp test <tool> [input_json] --json` | Test an MCP tool locally. | `--json` |
| `mcp tools --json` | List available MCP tools. | `--json` |

---

## Metrics Commands

| Command | Description | Options |
|---------|-------------|---------|
| `metrics accuracy --json` | Show estimation accuracy report. | `--json` |
| `metrics breakdown --by --json` | Show cost breakdown by dimension. | `--by`, `--json` |
| `metrics budget --json` | Show budget status. | `--json` |
| `metrics burndown --sprint --start --end --json` | Generate burndown chart data for a sprint. | `--sprint`, `--start`, `--end`, `--json` |
| `metrics export --output --format` | Export metrics to file. | `--output`, `--format` |
| `metrics summary --json` | Show metrics summary from telemetry data. | `--json` |
| `metrics task <task_id> --json` | Show metrics for a specific task. | `--json` |
| `metrics tokens --json` | Show token estimation accuracy report. | `--json` |
| `metrics velocity --weeks --json` | Show velocity metrics for project planning. | `--weeks`, `--json` |

---

## Migrate Commands

| Command | Description | Options |
|---------|-------------|---------|
| `migrate status` | Show current PairCoder version status. |  |

---

## Orchestrate Commands

| Command | Description | Options |
|---------|-------------|---------|
| `orchestrate analyze <task_id> --json` | Analyze a task and show routing decision. | `--json` |
| `orchestrate auto-run [task_id] --plan --pr --test --json` | Run autonomous workflow for a single task. | `--plan`, `--pr`, `--test`, `--json` |
| `orchestrate auto-session --plan --max --pr --json` | Run autonomous session processing multiple tasks. | `--plan`, `--max`, `--pr`, `--json` |
| `orchestrate evaluate <event> --agent-id --agent-type --quiet` | Evaluate orchestration stop conditions; outputs JSON for CC hooks. | `--agent-id`, `--agent-type`, `--quiet` |
| `orchestrate handoff <task_id> --to --summary --out` | Create a handoff package for another agent. | `--to`, `--summary`, `--out` |
| `orchestrate select-agent <task_id> --prefer --json` | Select the best specialized agent for a task. | `--prefer`, `--json` |
| `orchestrate task <task_id> --prefer --max-cost --dry-run --json` | Orchestrate a task to the best agent. | `--prefer`, `--max-cost`, `--dry-run`, `--json` |
| `orchestrate workflow-status --json` | Show current autonomous workflow status. | `--json` |

---

## Plan Commands

| Command | Description | Options |
|---------|-------------|---------|
| `plan add-task <plan_id> --id --title --type --priority --complexity --sprint` | Add a task to a plan. | `--id`, `--title`, `--type`, `--priority`, `--complexity`, `--sprint` |
| `plan complete <plan_id> --force` | Mark a plan as complete. | `--force` |
| `plan estimate <plan_id> --threshold --json --show-tasks` | Estimate token usage for a plan and suggest batching if needed. | `--threshold`, `--json`, `--show-tasks` |
| `plan list --status --json` | List all plans. | `--status`, `--json` |
| `plan new <slug> --type --title --skill --flow --goal --scope --feature-id --total-cx` | Create a new plan. | `--type`, `--title`, `--skill`, `--flow`, `--goal`, `--scope`, `--feature-id`, `--total-cx` |
| `plan show <plan_id> --json` | Show details of a specific plan. | `--json` |
| `plan status [plan_id] --verbose --json` | Show plan status with sprint/task breakdown. | `--verbose`, `--json` |
| `plan sync-pm <plan_id> --board --target-list --create-lists --link --apply-defaults --only-new --fire-ready --dry-run --json` | Sync plan tasks to PM provider (or Trello directly). | `--board`, `--target-list`, `--create-lists`, `--link`, `--apply-defaults`, `--only-new`, `--fire-ready`, `--dry-run`, `--json` |
| `plan sync-trello <plan_id> --board --target-list --create-lists --link --apply-defaults --only-new --fire-ready --dry-run --json` | Sync plan tasks to PM provider (or Trello directly). (DEPRECATED) | `--board`, `--target-list`, `--create-lists`, `--link`, `--apply-defaults`, `--only-new`, `--fire-ready`, `--dry-run`, `--json` |
| `plan tasks <plan_id> --status --json` | List tasks for a specific plan. | `--status`, `--json` |

---

## PM Commands

| Command | Description | Options |
|---------|-------------|---------|
| `pm action <action_name> <item_id>` | Execute a button action on a work item. |  |
| `pm block <item_id> --reason` | Block a work item with a reason. | `--reason` |
| `pm check <item_id> <checklist_item_id> --uncheck` | Check or uncheck a checklist item. | `--uncheck` |
| `pm children <parent_id>` | List children of a work item. |  |
| `pm comment <item_id> <message>` | Add a comment to a work item. |  |
| `pm config` | Show resolved PM workflow configuration. |  |
| `pm create --type --title --parent` | Create a new work item via the PM provider. | `--type`, `--title`, `--parent` |
| `pm diagnostics` | Run PM provider diagnostics. |  |
| `pm done <item_id> --summary --strict` | Complete a work item (move to done). | `--summary`, `--strict` |
| `pm link <parent_id> <child_ids>` | Link child items to a parent (set parent-child relationship). |  |
| `pm move <item_id> --status` | Move a work item to a new status. | `--status` |
| `pm set-field <item_id> --field --value` | Set a custom field on a work item. | `--field`, `--value` |
| `pm sprint complete <plan_id> --carry-forward` | Complete a sprint — evaluate tasks and produce summary. | `--carry-forward` |
| `pm sprint start <plan_id>` | Start a sprint (mark plan as in-progress). |  |
| `pm start <item_id>` | Start a work item (move to in_progress). |  |
| `pm status` | Show PM provider connection status. |  |
| `pm sync` | Sync local tasks to the PM provider. |  |
| `pm tree <root_id>` | Display hierarchy tree of a work item. |  |
| `pm unlink <child_id>` | Remove parent relationship from an item. |  |

---

## Preset Commands

| Command | Description | Options |
|---------|-------------|---------|
| `preset list --json` | List available configuration presets. | `--json` |
| `preset preview <name> --name --goal` | Preview the config.yaml that would be generated. | `--name`, `--goal` |
| `preset show <name> --json` | Show details for a specific preset. | `--json` |

---

## QA Commands

| Command | Description | Options |
|---------|-------------|---------|
| `qa init` | [DEPRECATED] Use 'bpsai-pair qc init'. |  |
| `qa list --tags --json` | [DEPRECATED] Use 'bpsai-pair qc list'. | `--tags`, `--json` |
| `qa report --json` | [DEPRECATED] Use 'bpsai-pair qc report'. | `--json` |
| `qa validate --json` | [DEPRECATED] Use 'bpsai-pair qc validate'. | `--json` |

---

## QC Commands

| Command | Description | Options |
|---------|-------------|---------|
| `qc init` | Initialize QC directory structure with example config and suite. |  |
| `qc list --tags --json` | List discovered QC test suites. | `--tags`, `--json` |
| `qc report --json` | Display results from the last QC run. | `--json` |
| `qc validate --json` | Validate all QC suite specs. | `--json` |

---

## Query Commands

| Command | Description | Options |
|---------|-------------|---------|
| `query metrics <name> --task-type --days --json` | Query metrics (success rates, estimation accuracy, agent performance). | `--task-type`, `--days`, `--json` |
| `query qc-trends --suite --env --json` | Query QC historical trends and flaky scenarios. | `--suite`, `--env`, `--json` |
| `query skill <name> --format --root` | Execute a query skill and output results. | `--format`, `--root` |
| `query state <key> --json` | Query project state (active tasks, current plan). | `--json` |
| `query task-state --task-id --plan-id --state --json` | Query task state transitions (pending → in_progress → done). | `--task-id`, `--plan-id`, `--state`, `--json` |
| `query tasks --status --json` | Query tasks with optional status filter. | `--status`, `--json` |

---

## Release Commands

| Command | Description | Options |
|---------|-------------|---------|
| `release checklist` | Show the release preparation checklist. |  |
| `release plan --sprint --version --create` | Generate release preparation tasks. | `--sprint`, `--version`, `--create` |
| `release prep --since --create-tasks --skip-tests` | Verify release readiness and generate tasks for missing items. | `--since`, `--create-tasks`, `--skip-tests` |
| `release record-phase89 --website-repo --fleet-verified` | Record Phase 8/9 completion. | `--website-repo`, `--fleet-verified` |
| `release validate-versions --fix` | Check version consistency across config files. | `--fix` |
| `release verify-phase89` | Fail closed if the Phase 8/9 (website+fleet) completion artifact is missing or stale relative to... |  |

---

## Review Commands

| Command | Description | Options |
|---------|-------------|---------|
| `review auto [query] --json` | Auto-route a review request to the correct subcommand. | `--json` |
| `review branch --base --json` | Review the current branch diff against base (pre-PR validation). | `--base`, `--json` |
| `review pr <number> --post --json` | Review a GitHub PR by number. | `--post`, `--json` |
| `review sprint <sprint_id> --json` | Fleet review for a cross-repo sprint: review every touched repo's PR, audit cross-repo contracts,... | `--json` |
| `review task [task_id] --json` | Review a single task's changes. | `--json` |

---

## Security Commands

| Command | Description | Options |
|---------|-------------|---------|
| `security install-hook --overwrite` | Install pre-commit hook for secret scanning. | `--overwrite` |
| `security pre-commit --json` | Run secret scan as a pre-commit hook. | `--json` |
| `security scan-deps [path] --fail-on --verbose --json --no-cache` | Scan dependencies for known vulnerabilities. | `--fail-on`, `--verbose`, `--json`, `--no-cache` |
| `security scan-secrets [path] --staged --diff --verbose --json` | Scan for secrets and credentials in code. | `--staged`, `--diff`, `--verbose`, `--json` |

---

## Session Commands

| Command | Description | Options |
|---------|-------------|---------|
| `session check --force --quiet` | Check session state and display context if new session. | `--force`, `--quiet` |
| `session set-role <role>` | Set the active agent role for status line display. |  |
| `session status --budget` | Show current session status including token budget. | `--budget` |

---

## Setup Commands

| Command | Description | Options |
|---------|-------------|---------|
| `setup statusline --theme --remove --preview` | Configure the PairCoder status line for Claude Code. | `--theme`, `--remove`, `--preview` |

---

## Skill Commands

| Command | Description | Options |
|---------|-------------|---------|
| `skill export [skill_name] --format --all --dry-run` | Export skills to other AI coding tool formats. | `--format`, `--all`, `--dry-run` |
| `skill gaps --json --clear --analyze` | List detected skill gaps from session history. | `--json`, `--clear`, `--analyze` |
| `skill generate [gap_id] --auto-approve --overwrite --preview` | Generate a skill from a detected gap. | `--auto-approve`, `--overwrite`, `--preview` |
| `skill install <source> --project --personal --name --overwrite` | Install a skill from URL or local path. | `--project`, `--personal`, `--name`, `--overwrite` |
| `skill list --json` | List all skills in .claude/skills/. | `--json` |
| `skill recommend --top --format --verbose` | Recommend skills based on intelligence signals. | `--top`, `--format`, `--verbose` |
| `skill score [skill_name] --json` | Score skills on quality dimensions. | `--json` |
| `skill suggest --json --create --min` | Analyze session history and suggest new skills. | `--json`, `--create`, `--min` |
| `skill validate [skill_name] --fix --json` | Validate skills against Anthropic specs. | `--fix`, `--json` |

---

## Sprint Commands

| Command | Description | Options |
|---------|-------------|---------|
| `sprint complete <sprint_id> --skip-checklist --reason --plan --archive` | Complete a sprint with checklist verification and optional archival. | `--skip-checklist`, `--reason`, `--plan`, `--archive` |
| `sprint list --plan` | List sprints in a plan. | `--plan` |

---

## Standup Commands

| Command | Description | Options |
|---------|-------------|---------|
| `standup generate --plan --since --format --output` | Generate a daily standup summary. | `--plan`, `--since`, `--format`, `--output` |
| `standup post --plan --since` | Post standup summary to Trello board's Notes list. | `--plan`, `--since` |

---

## State Commands

| Command | Description | Options |
|---------|-------------|---------|
| `state advance <task_id> <to_state> --reason` | Manually advance task to a new state. | `--reason` |
| `state history [task_id] --limit` | Show state transition history. | `--limit` |
| `state list --status` | List all tracked task states. | `--status` |
| `state reset <task_id> --yes` | Reset a task to NOT_STARTED state. | `--yes` |
| `state show <task_id>` | Show current execution state for a task. |  |
| `state validate --quiet --task --full` | Validate that tasks marked done in state.md are actually complete. | `--quiet`, `--task`, `--full` |

---

## Subagent Commands

| Command | Description | Options |
|---------|-------------|---------|
| `subagent gaps --json --clear --analyze` | List detected subagent gaps from session history. | `--json`, `--clear`, `--analyze` |

---

## Subscription Commands

| Command | Description | Options |
|---------|-------------|---------|
| `subscription manage --no-browser --return-url --json` | Open the Stripe Billing Portal to manage your subscription. | `--no-browser`, `--return-url`, `--json` |
| `subscription status --json` | Show your subscription status. | `--json` |

---

## Support Commands

| Command | Description | Options |
|---------|-------------|---------|
| `support create --type --title --description --json` | Create a support ticket with auto-attached system info. | `--type`, `--title`, `--description`, `--json` |
| `support list --status --json` | List your support tickets. | `--status`, `--json` |
| `support open --no-browser --verbose` | Open support portal with auto-login. | `--no-browser`, `--verbose` |
| `support show <ticket_id> --json` | Show a specific support ticket with comments. | `--json` |

---

## System Commands

| Command | Description | Options |
|---------|-------------|---------|
| `system info --json` | Show local environment info (version, Python, OS) for bug reports. | `--json` |

---

## Task Commands

| Command | Description | Options |
|---------|-------------|---------|
| `task ac <task_id> --plan` | Show acceptance criteria status for a task. | `--plan` |
| `task archive [task_ids] --completed --sprint --plan --version --no-changelog --dry-run` | Archive completed tasks. | `--completed`, `--sprint`, `--plan`, `--version`, `--no-changelog`, `--dry-run` |
| `task auto-next --plan` | Automatically assign and start the next pending task. | `--plan` |
| `task changelog-preview --sprint --plan --version` | Preview changelog entry for tasks. | `--sprint`, `--plan`, `--version` |
| `task check <task_id> [item_text] --uncheck --plan` | Check or uncheck acceptance criteria items. | `--uncheck`, `--plan` |
| `task cleanup --retention --dry-run` | Clean up old archived tasks. | `--retention`, `--dry-run` |
| `task done <task_id> --plan --no-hooks` | Mark a task as done (updates task file + runs consistency check). | `--plan`, `--no-hooks` |
| `task list --plan --status --json` | List tasks. | `--plan`, `--status`, `--json` |
| `task list-archived --plan --json` | List archived tasks. | `--plan`, `--json` |
| `task next --start` | Show the next task to work on. | `--start` |
| `task restore <task_id> --plan` | Restore a task from archive. | `--plan` |
| `task show <task_id> --plan` | Show details of a specific task. | `--plan` |
| `task update <task_id> --status --plan --no-hooks --skip-state-check --resync --local-only --reason --strict --force-local --auto-check --allow-dirty` | Update a task's status. | `--status`, `--plan`, `--no-hooks`, `--skip-state-check`, `--resync`, `--local-only`, `--reason`, `--strict`, `--force-local`, `--auto-check`, `--allow-dirty` |

---

## Telemetry Commands

| Command | Description | Options |
|---------|-------------|---------|
| `telemetry aggregate --workspace --format --output --since --include-garbage --json` | Aggregate telemetry across all repos in a workspace. | `--workspace`, `--format`, `--output`, `--since`, `--include-garbage`, `--json` |
| `telemetry config --enable --disable --privacy --retention --json` | Configure telemetry settings. | `--enable`, `--disable`, `--privacy`, `--retention`, `--json` |
| `telemetry export --format --output --since --until --task-type --anonymize` | Export telemetry data for analysis or backup. | `--format`, `--output`, `--since`, `--until`, `--task-type`, `--anonymize` |
| `telemetry log-failure --trigger --quiet` | Log an API failure signal to telemetry. | `--trigger`, `--quiet` |
| `telemetry log-session-end --outcome-summary --stop-reason --session-id --quiet` | Log a session_end (info) signal. | `--outcome-summary`, `--stop-reason`, `--session-id`, `--quiet` |
| `telemetry log-subagent-outcome --stop-reason --agent-id --agent-type --session-id --quiet` | Log a subagent_outcome (info) signal. | `--stop-reason`, `--agent-id`, `--agent-type`, `--session-id`, `--quiet` |
| `telemetry recover <archive_dir> --dry-run --project` | Recover historical telemetry from Claude session archives. | `--dry-run`, `--project` |
| `telemetry status --json` | Show telemetry collection status and statistics. | `--json` |

---

## Template Commands

| Command | Description | Options |
|---------|-------------|---------|
| `template check --fail-on-drift --fix --verbose` | Check for drift between source files and cookie cutter template. | `--fail-on-drift`, `--fix`, `--verbose` |
| `template list` | List files tracked for template sync. |  |

---

## Timer Commands

| Command | Description | Options |
|---------|-------------|---------|
| `timer show <task_id> --json` | Show time entries for a task. | `--json` |
| `timer start <task_id> --description` | Start a timer for a task. | `--description` |
| `timer status` | Show current timer status. |  |
| `timer stop` | Stop the current timer. |  |
| `timer summary --plan --json` | Show time summary across tasks. | `--plan`, `--json` |

---

## Trello Commands

| Command | Description | Options |
|---------|-------------|---------|
| `trello apply-defaults <card_id>` | Apply project default values to a Trello card. |  |
| `trello boards --json` | List available Trello boards. | `--json` |
| `trello config --show --set-list --set-field --agent` | View or modify Trello configuration. | `--show`, `--set-list`, `--set-field`, `--agent` |
| `trello connect --api-key --token` | Connect to Trello (validates and stores credentials). | `--api-key`, `--token` |
| `trello disconnect` | Remove stored Trello credentials. |  |
| `trello fields --board --refresh --json` | Show custom fields and their valid options for a board. | `--board`, `--refresh`, `--json` |
| `trello init-board --name --from-template --keep-cards --set-active` | Create a new Trello board from a template. | `--name`, `--from-template`, `--keep-cards`, `--set-active` |
| `trello list-fields` | List all custom fields on the active board (table format). |  |
| `trello lists` | Show lists on the active board. |  |
| `trello progress <task_id> [message] --blocked --waiting --step --started --completed --review --agent` | Post a progress comment to a Trello card. | `--blocked`, `--waiting`, `--step`, `--started`, `--completed`, `--review`, `--agent` |
| `trello set-field <card_id> --project --stack --status --effort --repo-url --field --value` | Set custom field values on a Trello card. | `--project`, `--stack`, `--status`, `--effort`, `--repo-url`, `--field`, `--value` |
| `trello status` | Check Trello connection status. |  |
| `trello sync --from-trello --preview --list` | Sync tasks between Trello and local files. | `--from-trello`, `--preview`, `--list` |
| `trello use-board <board_id>` | Set the active Trello board for this project. |  |
| `trello webhook delete <webhook_id>` | Delete a registered webhook. |  |
| `trello webhook list` | List all registered webhooks for the current token. |  |
| `trello webhook register <callback_url> --board` | Register a webhook with Trello. | `--board` |
| `trello webhook serve --host --port --agent --auto-assign --verbose` | Start the Trello webhook server with agent assignment. | `--host`, `--port`, `--agent`, `--auto-assign`, `--verbose` |

---

## Ttask Commands

| Command | Description | Options |
|---------|-------------|---------|
| `ttask block <card_id> --reason` | Mark a task as blocked. | `--reason` |
| `ttask check <task_id> <item_text> --checklist` | Check off a checklist item as complete. | `--checklist` |
| `ttask comment <task_id> <message>` | Add a progress comment to a task. |  |
| `ttask done <card_id> --summary --list --auto-check --strict --allow-dirty` | Complete a task (moves to Done list). | `--summary`, `--list`, `--auto-check`, `--strict`, `--allow-dirty` |
| `ttask list --list --agent --status` | List tasks from Trello board. | `--list`, `--agent`, `--status` |
| `ttask move <card_id> --list` | Move a task to a different list. | `--list` |
| `ttask show <card_id>` | Show task details from Trello. |  |
| `ttask start <card_id> --summary --budget-override` | Start working on a task (moves to In Progress). | `--summary`, `--budget-override` |
| `ttask uncheck <task_id> <item_text> --checklist` | Uncheck a checklist item (mark as incomplete). | `--checklist` |

---

## Workspace Commands

| Command | Description | Options |
|---------|-------------|---------|
| `workspace audit <project> --fix --json` | Run a full audit of a sibling project. | `--fix`, `--json` |
| `workspace check-impact --since --json` | Check contract changes and their cross-repo impact. | `--since`, `--json` |
| `workspace index --topic --json` | Query the workspace document index by topic. | `--topic`, `--json` |
| `workspace init --name --projects --scan --no-scan --force --json` | Initialize a new workspace configuration. | `--name`, `--projects`, `--scan`, `--no-scan`, `--force`, `--json` |
| `workspace init-project [name] --all --force --dry-run --json --no-claude` | Initialize a project in the workspace with PairCoder scaffolding. | `--all`, `--force`, `--dry-run`, `--json`, `--no-claude` |
| `workspace pull [project] --rebase --json` | Pull latest changes from remote for workspace projects. | `--rebase`, `--json` |
| `workspace setup-permissions --dry-run --force --json` | Generate .claude/settings.local.json from workspace config. | `--dry-run`, `--force`, `--json` |
| `workspace status --json` | Show workspace configuration and project states. | `--json` |
| `workspace validate --repo --json` | Validate the covering workspace config (CI-usable). | `--repo`, `--json` |
