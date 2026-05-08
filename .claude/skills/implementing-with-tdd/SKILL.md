---
name: implementing-with-tdd
description: Use when implementing bug fixes, features, or any code changes where test-first development is appropriate.
skills: [implementing-with-tdd]
agent-roles: [driver]
---

# TDD Implementation — Incremental Red-Green-Refactor

## Philosophy

Write ONE small test, make it pass, refactor, repeat. Never write all tests upfront.

## Phase 1: Cycle Planning (Before Any Code)

Before writing a single line of code:

1. **Read the task's acceptance criteria (AC)** — each AC item is roughly one cycle
2. **Decompose into behaviors** — break each AC into 1-3 testable behaviors
3. **Plan test files** — if you expect >15 test functions total, plan multiple files now:
   - Name by behavior: `test_parser_validation.py`, `test_parser_edge_cases.py`
   - NOT one monolith: ~~`test_parser.py`~~
4. **Order behaviors** — simplest first, building toward complex (each cycle builds on the last)

**Example cycle plan for a parser task:**
```
Cycle 1: parse empty input → returns empty result (1 test)
Cycle 2: parse single valid entry → returns correct fields (2 tests)
Cycle 3: parse malformed input → raises ValueError (2 tests)
Cycle 4: parse batch input → handles multiple entries (2 tests)
```

## Phase 2: The Cycle (Repeat for Each Behavior)

### RED — Write 1-3 Test Functions

Write tests for ONE behavior only. Maximum 5 test functions per RED phase.

```bash
# Run the new tests — they MUST fail
pytest tests/path/to/test_file.py -v -k "test_new_behavior"
```

**If tests pass without implementation, the tests are wrong.** Fix them.

### GREEN — Write Minimum Code to Pass

Write ONLY enough production code to make the failing tests pass. No more.

```bash
# Run tests — they must now pass
pytest tests/path/to/test_file.py -v
```

### REFACTOR — Clean Up While Green

If files are growing large, refactor NOW (not later):
- Extract helpers to separate modules
- Split test files at 15 functions
- Ensure test file stays under 600 lines, production file under 400 lines

```bash
# Tests must still pass after refactor
pytest tests/path/to/test_file.py -v
```

### CHECKPOINT — Every 3-5 Cycles

After every 3-5 completed cycles, run architecture check:

```bash
bpsai-pair arch check <modified-production-files>
```

Fix any violations before continuing to the next cycle.

## Anti-Patterns (DO NOT)

- **DO NOT** write more than 5 test functions before implementing
- **DO NOT** write all tests for a task before any implementation
- **DO NOT** rewrite failing tests to match incorrect implementation — **fix the implementation first**. If a test was written as a spec for a behavior, the test is probably right
- **DO NOT** let a single test file exceed 600 lines without splitting
- **DO NOT** let a production file exceed 400 lines without decomposing

## Test File Organization

| Guideline | Rule |
|-----------|------|
| Naming | Name by behavior, not just module: `test_parser_validation.py` |
| Split point | Create a new file when reaching 15 test functions |
| Fixtures | Share via `conftest.py` when used by 2+ test files |
| Imports | Keep under 30 per test file |
| Line count | Warning at 400, error at 600 (relaxed from production limits) |

## Project Test Commands

```bash
# Run specific test
pytest tests/path/test_module.py::test_function -v

# Run all tests
pytest -v

# Run with coverage
pytest --cov

# Run only failed tests
pytest --lf

# Stop on first failure
pytest -x
```

## Architecture Compliance

**MANDATORY:** Before completing any task:

```bash
bpsai-pair arch check <path-to-modified-files>
```

Test files have relaxed limits (600/400/50/40/30) but still enforced.
Production files have strict limits (400/200/50/15/20).

See also: `architecting-modules` skill for decomposition patterns.

## Task Completion

After all cycles complete, tests pass, AND arch check passes:
1. `bpsai-pair ttask done TRELLO-XX --summary "..."`
2. Update `.paircoder/context/state.md` (NON-NEGOTIABLE)
