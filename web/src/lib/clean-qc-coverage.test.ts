/**
 * The /methodology cross-check figures (issue #140).
 *
 * Percentages must describe pages the judge actually assessed. Pages the
 * judge could not evaluate (`runner_errors`) and pages whose outcome is
 * unknown (`indeterminate_pages`) are recorded inside `operator_review` by
 * the producer, so they come out of both the denominator and the
 * operator-review tally.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanQcCoverage, describeCleanQcAssessment } from "./clean-qc-coverage.ts";

test("cleanQcCoverage: runner errors and indeterminate pages are excluded from the assessed figures", () => {
  const c = cleanQcCoverage({
    total_pages: 1000,
    judge_ok: 600,
    operator_review: 400,
    runner_errors: 150,
    indeterminate_pages: 50,
  });
  assert.equal(c.assessedPages, 800);
  assert.equal(c.unevaluatedPages, 200);
  assert.equal(c.judgeOk, 600);
  assert.equal(c.operatorReview, 200);
  assert.equal(c.judgeOkPct, 75);
  assert.equal(c.operatorReviewPct, 25);
});

test("cleanQcCoverage: a bundle without the fields falls back to the whole-page figures", () => {
  const c = cleanQcCoverage({ total_pages: 1000, judge_ok: 600, operator_review: 400 });
  assert.equal(c.reportsUnevaluated, false);
  assert.equal(c.assessedPages, 1000);
  assert.equal(c.unevaluatedPages, 0);
  assert.equal(c.operatorReview, 400);
  assert.equal(c.judgeOkPct, 60);
  assert.equal(c.operatorReviewPct, 40);
  assert.equal(describeCleanQcAssessment(c), "");
});

test("cleanQcCoverage: v10's published stats (111 runner errors)", () => {
  const c = cleanQcCoverage({
    total_pages: 11268,
    judge_ok: 6524,
    operator_review: 4744,
    runner_errors: 111,
    indeterminate_pages: 0,
  });
  assert.equal(c.assessedPages, 11157);
  assert.equal(c.unevaluatedPages, 111);
  assert.equal(c.operatorReview, 4633);
  assert.equal(c.judgeOkPct, 58);
  assert.equal(c.operatorReviewPct, 42);
  assert.equal(
    describeCleanQcAssessment(c),
    "11,157 pages assessed; 111 could not be evaluated.",
  );
});

test("cleanQcCoverage: v11's published stats (every page assessed)", () => {
  const c = cleanQcCoverage({
    total_pages: 11268,
    judge_ok: 6573,
    operator_review: 4695,
    runner_errors: 0,
    indeterminate_pages: 0,
  });
  assert.equal(c.reportsUnevaluated, true);
  assert.equal(c.assessedPages, 11268);
  assert.equal(c.unevaluatedPages, 0);
  assert.equal(c.operatorReview, 4695);
  assert.equal(c.judgeOkPct, 58);
  assert.equal(c.operatorReviewPct, 42);
  assert.equal(describeCleanQcAssessment(c), "All 11,268 pages were assessed.");
});

test("cleanQcCoverage: a run where the judge reached no page reports no percentages", () => {
  const c = cleanQcCoverage({
    total_pages: 10,
    judge_ok: 0,
    operator_review: 10,
    runner_errors: 10,
    indeterminate_pages: 0,
  });
  assert.equal(c.assessedPages, 0);
  assert.equal(c.operatorReview, 0);
  assert.equal(c.judgeOkPct, null);
  assert.equal(c.operatorReviewPct, null);
  assert.equal(describeCleanQcAssessment(c), "0 pages assessed; 10 could not be evaluated.");
});
