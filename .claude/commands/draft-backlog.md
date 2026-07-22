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

Each task MAY also declare (engage reads these per task):
- **Target repo:** a bare sibling name (e.g. `bpsai-computer`) or path for a
  cross-repo task. Sets where engage dispatches this task. A whole-run override
  is available as `bpsai-pair engage <file> --target-repo <path>`, which
  REFUSES if a per-task **Target repo:** names a different repo — so keep
  per-task lines consistent with any intended override.
- **Base:** the base branch this task's work should build on (per-task override
  of the backlog-level `**Base:**`).

### Engage-compatible line rules (do NOT break these)

- **One physical line per AC.** Write each `- [ ]` criterion on a SINGLE line.
  Do not wrap a criterion across indented continuation lines — the materializer
  now folds indented continuations into the item, but a single line is
  unambiguous and avoids accidental joins with a following note (#627).
- **Bare `**Depends on:**` values.** List dependencies as bare task IDs,
  comma-separated (e.g. `**Depends on:** T1.1, T1.2`), or `None`. No prose, no
  links, no wrapped continuation.
- **One `**Target repo:**` / `**Base:**` value per line**, no continuation.

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
9. Emit a plan record so `plan list`/`status` can see this lane (#609):
   `bpsai-pair plan ensure-from-backlog plans/backlogs/<filename>.md`

## Validation

After writing the backlog, ALWAYS run:
```bash
bpsai-pair engage plans/backlogs/<filename>.md --dry-run
```

If it fails, fix the format and retry until it passes.

## Plan Record (#609)

`draft-backlog` must emit a plan record alongside the backlog markdown,
just like `pc-plan`/`plan new` does — a user can't be relied on to
remember to draft one separately. After the dry-run validates, run:

```bash
bpsai-pair plan ensure-from-backlog plans/backlogs/<filename>.md
```

This is idempotent: if a plan record already exists for the derived id it
is left untouched.
