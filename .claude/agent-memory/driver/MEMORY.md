# Driver Memory

> This file is automatically loaded into the Driver agent's system prompt (first 200 lines).
> Record implementation patterns, mock strategies, and coding pitfalls specific to this project.

## Architecture Constraints
- **Lines**: <400 error, <200 warning (test files: <600/<400)
- **Functions**: <50 lines, <15 per file (test files: <30)
- **Imports**: <20 per file (test files: <40)
- Run `bpsai-pair arch check <path>` before completing any task

## TDD Workflow
- One behavior at a time: write failing test → minimal code → refactor → repeat
- Never write all tests upfront
- Run from project root: `python -m pytest tests/ -v`

## Patterns Learned
<!-- Add project-specific patterns as you discover them -->
