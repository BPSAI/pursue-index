# Architecture Constraints

Run `bpsai-pair arch check <path>` before completing any code task. Fix all errors before marking done.

## File Limits

| Metric | Source Files | Test Files |
|--------|-------------|------------|
| Lines (error) | < 400 | < 600 |
| Lines (warning) | < 200 | < 400 |
| Function length | < 50 lines | < 50 lines |
| Functions per file | < 15 | < 30 |
| Imports per file | < 20 | < 40 |

## Key Rules

- `arch check` counts ALL functions in a file, including module-level helpers
- Extract helpers to a separate module to fix function count violations
- Run from project root: `bpsai-pair arch check <path/to/file.py>`
- Use the `architecting-modules` skill for decomposition guidance
