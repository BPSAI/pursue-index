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
- **Opus 5.5 differences.** Thinking is always on (default effort `medium`) and
  thinking tokens count against `max_tokens`. The 5.5 calls therefore use
  `max_tokens=16000` (the pinned model keeps 2048), and `--effort` can set
  `output_config.effort`. Every call records `stop_reason`; `max_tokens` counts
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

# attended, spends money; the cap is required
python scripts/vision_model_bakeoff.py --live --hard-cap-usd <usd>
```

`--live` refuses without a cap, refuses under CI, and refuses before spending if
any selected page has no local image. Each call is metered from the response's
usage at $5/$25 per MTok (Opus 4.8) and $4/$20 (Opus 5.5). The run stops before
any call whose worst case (full `max_tokens` of output) would pass the cap.
Output goes to `--out-dir` (`results.json`, `report.md`).

## Results

_Not yet run._

| Model | Pages | Completeness | Text agreement | Claim overlap | Truncated | Refusals | Cost |
|---|---|---|---|---|---|---|---|
| claude-opus-4-8 | | | | | | | |
| claude-opus-5-5 | | | | | | | |

Spot-check notes:

Recommendation:
