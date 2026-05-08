---
name: architecting-modules
description: Guides module architecture decisions including file size limits, function boundaries, and modular design patterns to maintain code quality and prevent complexity creep.
skills: [architecting-modules]
agent-roles: [driver, nayru]
---

# Architecting Modules

## When to Use

Triggers on these patterns:
- "create", "add feature", "implement", "build"
- "refactor", "split", "extract", "modularize"
- Adding significant new functionality
- Working on files approaching size limits

**Pre-check**: Before modifying any file >150 lines, review this skill.

---

## File Size Limits

| Threshold | Lines | Action |
|-----------|-------|--------|
| **Target** | <200 | Ideal size, no action needed |
| **Warning** | 200-400 | Consider extraction opportunities |
| **Must-split** | >400 | Split before adding new code |

### Quick Check

```bash
# Check file line count
wc -l path/to/file.py

# Find large files in a directory
find src/ -name "*.py" -exec wc -l {} + | sort -n | tail -20
```

---

## Function Limits

| Threshold | Lines | Action |
|-----------|-------|--------|
| **Target** | <30 | Ideal, easily testable |
| **Acceptable** | 30-50 | Consider extraction if adding logic |
| **Must-split** | >50 | Extract helper functions |

### Signs a Function Needs Splitting

- Multiple levels of nesting (>3 levels)
- Multiple distinct responsibilities
- Hard to name (does too many things)
- Comments separating "sections" of logic
- Too many parameters (>5)

---

## Module Structure Patterns

### Hub-and-Spoke Pattern (Recommended)

Main module re-exports from focused sub-modules:

```
feature/
├── __init__.py      # Hub: public API exports
├── models.py        # Spoke: data structures
├── service.py       # Spoke: business logic
├── repository.py    # Spoke: data access
└── utils.py         # Spoke: helpers
```

**Hub (`__init__.py`):**
```python
from .models import User, UserCreate, UserUpdate
from .service import UserService
from .repository import UserRepository

__all__ = ["User", "UserCreate", "UserUpdate", "UserService", "UserRepository"]
```

**Benefits:**
- Clear public API
- Easy to test individual spokes
- Prevents circular imports
- Each file has single responsibility

### Layered Pattern

For larger features with clear boundaries:

```
feature/
├── api/              # HTTP/CLI interface
│   ├── routes.py
│   └── schemas.py
├── domain/           # Business logic
│   ├── models.py
│   └── services.py
├── infrastructure/   # External integrations
│   ├── database.py
│   └── external_api.py
└── __init__.py       # Public exports
```

---

## Anti-Patterns to Avoid

### God Objects

**Problem:** Single class/module handling too many responsibilities.

**Signs:**
- File >500 lines
- Class with >15 methods
- Methods with unrelated functionality
- Frequent merge conflicts

**Fix:** Extract cohesive groups of methods into separate classes.

### Circular Imports

**Problem:** Module A imports B, B imports A.

**Signs:**
- `ImportError` at runtime
- Need to import inside functions
- Confusing dependency graph

**Fix:**
1. Extract shared code to a third module
2. Use dependency injection
3. Move imports to function level (last resort)

### Deep Nesting

**Problem:** Too many levels of directories or conditionals.

**Signs:**
- >3 directory levels for small features
- Nested if/for statements >3 levels deep
- Hard to trace code flow

**Fix:**
- Flatten structure
- Use early returns
- Extract nested logic to functions

### Kitchen Sink Modules

**Problem:** `utils.py` or `helpers.py` that grows unbounded.

**Signs:**
- utils.py >200 lines
- Unrelated functions grouped together
- Hard to find specific helpers

**Fix:** Split by domain (`string_utils.py`, `date_utils.py`, `validation_utils.py`)

---

## Pre-Modification Checklist

Before adding code to an existing file:

1. **Check current size:**
   ```bash
   wc -l path/to/file.py
   ```

2. **Assess impact:**
   - Will this push file over 200 lines? → Consider extraction first
   - Will this push file over 400 lines? → Must extract first

3. **Identify extraction candidates:**
   - Look for logical groupings in the file
   - Find functions that could stand alone
   - Identify data structures that deserve their own home

4. **Plan modular structure:**
   - What's the public API?
   - What can be internal/private?
   - What's the dependency direction?

---

## Extraction Techniques

### Extract Function

When a code block is reusable or complex:

```python
# Before: nested logic in main function
def process_order(order):
    # validate
    if not order.items:
        raise ValueError("Empty order")
    if order.total < 0:
        raise ValueError("Invalid total")
    # ... more validation ...

    # process
    for item in order.items:
        # ... complex processing ...

# After: extracted validation
def _validate_order(order):
    if not order.items:
        raise ValueError("Empty order")
    if order.total < 0:
        raise ValueError("Invalid total")

def process_order(order):
    _validate_order(order)
    for item in order.items:
        # ... complex processing ...
```

### Extract Class

When functions share state or are always used together:

```python
# Before: related functions with shared parameters
def send_email(config, to, subject, body): ...
def send_bulk_email(config, recipients, subject, body): ...
def validate_email(config, address): ...

# After: cohesive class
class EmailService:
    def __init__(self, config):
        self.config = config

    def send(self, to, subject, body): ...
    def send_bulk(self, recipients, subject, body): ...
    def validate(self, address): ...
```

### Extract Module

When a group of related code grows too large:

```python
# Before: everything in user_service.py (400+ lines)
# user_service.py contains:
# - User model
# - UserCreate, UserUpdate schemas
# - UserService class
# - UserRepository class
# - Validation helpers

# After: split into focused modules
# models.py      - User model
# schemas.py     - UserCreate, UserUpdate
# service.py     - UserService
# repository.py  - UserRepository
# validation.py  - Validation helpers
```

---

## Decision Guide: When to Split

```
Adding new code to a file?
│
├─ File <200 lines? → Add directly, ensure function stays <30 lines
│
├─ File 200-400 lines?
│   ├─ New code related to existing? → Add, but note for future extraction
│   └─ New code could be separate? → Extract to new module first
│
└─ File >400 lines? → STOP. Extract first, then add.
```

---

## Commands Reference

```bash
# Check file sizes
wc -l path/to/file.py
find . -name "*.py" -exec wc -l {} + | sort -n

# Count functions in a file (Python)
grep -c "^def \|^    def " path/to/file.py

# Find files over threshold
find . -name "*.py" -exec sh -c 'test $(wc -l < "$1") -gt 400 && echo "$1"' _ {} \;
```

---

## Integration with Other Skills

- **implementing-with-tdd**: Apply size limits when writing new code
- **reviewing-code**: Check file/function sizes during review
- **designing-and-implementing**: Plan module structure before implementing
