# Vision model bake-off: claude-opus-4-8 vs claude-opus-5-5

This compares the pinned vision model (`VISION_MODEL`, claude-opus-4-8) with
claude-opus-5-5 on pages that already have an observation. Nothing here changes
the pinned model. The recommendation is written only after an attended run.

## Method

`scripts/vision_model_bakeoff.py` does the work.

- **Sample.** About 30 described pages, drawn from the sidecars in
  `web/src/data/image-observations/` whose `our_pass.model` is claude-opus-4-8.
  Selection is seeded (`--seed`) and independent of file order. It round-robins
  across photographs, illustrations, documents and other, and keeps at most two
  blank pages. The pool currently holds few document scans, so documents are
  thin; the sample says so in its page list.
- **Calls.** Each page goes once through `examine_image` per model, using the
  same prompt, image path and 1,568px cap as production. Only the model changes.
  The arms are input: `--models` takes a comma list of Claude model ids
  (default `claude-opus-4-8,claude-opus-5-5`); other providers are refused.
  `--price MODEL=IN/OUT` (dollars per MTok, repeatable) sets a rate; the two
  defaults are built in, and a model with no price is flagged in a dry run and
  refused in `--live`. Report and score columns are per arm.
- **Images.** Every sampled page must resolve to an image. Pages inside
  multi-page PDF cards render through the pipeline's own page renderer, from
  the downloaded PDF or else the mirrored archive bytes (set
  `PURSUE_DATA_ROOT` to the data root that holds `pdfs/`, `images/` and
  `r2-mirror/`). A page that cannot be resolved is replaced by another
  eligible one, so the sample stays full size and deterministic for the seed.
- **Opus 5.5 differences.** Thinking is always on (default effort `medium`) and
  thinking tokens count against `max_tokens`. The 5.5 calls therefore use
  `max_tokens=8000` with `output_config.effort` set to `medium` (the pinned
  model keeps 2048), and `--effort` can change the effort. Every call records `stop_reason`; `max_tokens` counts
  as truncated and `refusal` is recorded and not scored.
- **Scoring against the existing observation.** Field completeness (the four
  page fields), `visible_text` agreement (1 minus normalized edit distance on
  case- and whitespace-folded text, first 3,000 characters), and claim overlap
  (F1 of claims with a counterpart at token Jaccard >= 0.4). The existing
  observation is itself a model output, so scores measure agreement, not truth.
- **Human spot-check.** `report.md` lists every page with its image path, the
  existing observation and both outputs side by side. Ten pages are marked
  SPOT-CHECK; read those against the images.

## Running it

```
# plan and estimate only; no API call (the default)
python scripts/vision_model_bakeoff.py --dry-run

# attended, spends money; the cap pre-flight runs first
python scripts/vision_model_bakeoff.py --live [--hard-cap-usd <usd>]
```

`--hard-cap-usd` defaults to 8.00. `--live` refuses under CI, refuses before
spending if any arm has no price, and refuses to start (non-zero exit, naming
the arm) when the summed expected estimate across arms exceeds the cap or any
one arm's worst case (full `max_tokens` of output on every page) does. The
dry run prints both figures per arm and a PASS or REFUSE line. Once running,
each call is metered from the response's usage and the run stops before any
call whose worst case would pass the cap.
Output goes to `--out-dir` (`results.json`, `report.md`).

## Method exceptions

Some cards stay on their curated passes on purpose. The 32 helicopter-case
imagery cards (`helicopter-case-2025-imagery-a-series`, 8, and
`helicopter-case-2025-imagery-b-series`, 24) came from a curated multi-frame
study, not from an older model, so re-describing them with the pinned
`VISION_MODEL` would replace a method with a single-image pass.

`data/vision-method-exceptions.json` is the record. Each entry has `card_id`,
`reason`, `cluster_label` and `decided_at`. The rule:

- `pursue vision run --redescribe` refuses any listed card, by name, in the
  no-spend preflight and in the live run alike.
- `--override-method-exception` together with `--reason "<text>"` lifts the
  refusal for that invocation. Either flag alone is refused, and the override
  is echoed with its reason.
- The file fails closed: a missing or malformed file refuses the run instead of
  being read as an empty list.

## Results

_Not yet run._

| Model | Pages | Completeness | Text agreement | Claim overlap | Truncated | Refusals | Cost |
|---|---|---|---|---|---|---|---|
| claude-opus-4-8 | | | | | | | |
| claude-opus-5-5 | | | | | | | |

Spot-check notes:

Recommendation:
