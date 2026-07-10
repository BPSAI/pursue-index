---
description: Draft a backlog document in engage-compatible format
allowed-tools: Bash(bpsai-pair:*), Bash(cat:*), Read, Write, Edit
argument-hint: <description or rough notes file>
---

# Draft Backlog

Draft a sprint backlog from the provided description or notes file.

## Input
$ARGUMENTS

## Format Requirements

Each task MUST follow this exact format:
### {ID} — {Title} | Cx: {N} | P{0-2}

Where:
- ID: letters + numbers (e.g., T1.1, S44.1, AMU1.1)
- Title: brief description
- — (em dash, not --)
- Cx: complexity in context units
- P0/P1/P2: priority

Each task MUST have:
- **Description:** paragraph explaining what to build
- **AC:** acceptance criteria as checkboxes (- [ ] item)
- **Depends on:** task dependencies (if any)
- **Model:** the model to dispatch this task with (see below)

## Model Assignment (MR3.2)

For each task, resolve `**Model:**` before writing it:

```bash
bpsai-pair calibration recommend-model --task-type <type> --complexity <Cx> [--cross-module]
```

This prefers a confident calibration `recommended_model` (enough samples,
`bpsai_pair.orchestration.model_doctrine`) over the ratified doctrine
fallback (single source of truth — do not hardcode a separate mapping
here): `feature`/`bugfix`/`refactor` → sonnet, `chore`/mechanical work →
haiku, complex or cross-module tasks → opus.

## Workflow

1. Analyze the input (description or file)
2. Break into phases (### Phase N: title)
3. Create tasks with proper format, including `**Model:**` per task
4. Include a Delivery Summary table (with a Model column)
5. Include a Priority Order list
6. Validate: run `bpsai-pair engage <output-file> --dry-run`
7. If dry-run fails, fix formatting and retry
8. Deliver to plans/backlogs/

## Validation

After writing the backlog, ALWAYS run:
```bash
bpsai-pair engage plans/backlogs/<filename>.md --dry-run
```

If it fails, fix the format and retry until it passes.
