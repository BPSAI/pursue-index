---
name: reviewing-code
description: Use when reviewing code changes, checking PRs, or evaluating code quality.
skills: [reviewing-code]
agent-roles: [nayru, laverna, vaivora]
context: fork
---

# Code Review

## Review Pipeline

The review pipeline dispatches three specialized agents:
- **Nayru** (reviewer): code quality, correctness, best practices
- **Laverna** (security-auditor): security vulnerabilities, SOC2 compliance
- **Vaivora** (vaivora): cross-module contracts, dependency impact (large diffs only, >500 lines or >10 files)

Use the review command to get the proper 3-agent pipeline:
```bash
bpsai-pair review pr <number>
bpsai-pair review branch
```

**IMPORTANT:** Do NOT dispatch generic agents for review. The review command handles agent dispatch with proper mythology names, severity-aware output, and size-scaled Vaivora dispatch. If you are already inside a review command invocation, do not duplicate the dispatch -- the command handles it.

## Quick Commands

```bash
# Run ALL checks at once (tests + linting)
bpsai-pair ci

# Validate project structure
bpsai-pair validate

# See what changed
git diff main...HEAD --stat
git diff main...HEAD
```

## Review Output Format

```markdown
## Code Review: [Description]

### Summary
Brief assessment.

### P0 (blocks merge -- breaking state, auto-reject)
1. **[File:Line]** - Issue and fix

### P1 (fix before merge -- quality issue, not breaking)
1. **[File:Line]** - Suggestion

### P2 (fix before merge -- lower priority improvement)
1. **[File:Line]** - Optional improvement

### Positive Notes
- What was done well

### Verdict
- [ ] Approve
- [ ] Approve with comments
- [ ] Request changes
```

## Project-Specific Checks

- Type hints on public functions
- Docstrings on public interfaces
- No hardcoded values (use config)
- Tests for new functionality
- Mock external services (Trello, GitHub APIs)
- Follow existing patterns in codebase

## Quick Checks

```bash
# Find debug statements
git diff main...HEAD | grep -E "print\(|breakpoint|pdb"

# Find TODOs in changes
git diff main...HEAD --name-only | xargs grep -n "TODO\|FIXME"

# Check for secrets
git diff main...HEAD | grep -iE "password|secret|api.?key|token"
```
