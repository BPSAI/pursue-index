/**
 * Cross-check coverage figures for /methodology (issue #140).
 *
 * The clean-QC bundle's verdict tallies count every page, including pages
 * the judge never assessed. The producer records those as
 * `operator-review` rows and counts them separately:
 *
 *   - `runner_errors`       — the judge could not evaluate the page (API
 *                             error, unrenderable page image).
 *   - `indeterminate_pages` — the judge did not read the page and the row
 *                             does not say why.
 *
 * Both are subsets of `operator_review`. The rule applied here:
 *
 *   assessed pages          = total_pages − runner_errors − indeterminate_pages
 *   assessed operator-review = operator_review − runner_errors − indeterminate_pages
 *   judge_ok                  (unchanged; an unassessed page is never ok)
 *
 * and both percentages are taken over assessed pages. Checked against the
 * published bundles: v10 had operator_review 4744 with runner_errors 111
 * and judge_ok 6524 (6524 + 4744 = total 11268, so the 111 sat inside
 * operator_review); v11 re-judged those 111 pages and reports
 * operator_review 4695, runner_errors 0, judge_ok 6573 — the same 11268.
 *
 * A bundle older than these fields falls back to the whole-page figures
 * and makes no claim either way about unevaluated pages.
 */

export interface CleanQcCoverageStats {
  total_pages: number;
  judge_ok: number;
  operator_review: number;
  runner_errors?: number;
  indeterminate_pages?: number;
}

export interface CleanQcCoverage {
  /** True when the bundle carries the unevaluated-page counts at all. */
  reportsUnevaluated: boolean;
  totalPages: number;
  assessedPages: number;
  /** runner_errors + indeterminate_pages. */
  unevaluatedPages: number;
  judgeOk: number;
  /** operator-review pages the judge actually assessed. */
  operatorReview: number;
  /** Percentages of assessed pages; null when no page was assessed. */
  judgeOkPct: number | null;
  operatorReviewPct: number | null;
}

export function cleanQcCoverage(stats: CleanQcCoverageStats): CleanQcCoverage {
  const reportsUnevaluated =
    stats.runner_errors !== undefined || stats.indeterminate_pages !== undefined;
  const unevaluatedPages = (stats.runner_errors ?? 0) + (stats.indeterminate_pages ?? 0);
  const assessedPages = Math.max(0, stats.total_pages - unevaluatedPages);
  const operatorReview = Math.max(0, stats.operator_review - unevaluatedPages);
  const pct = (n: number) => (assessedPages > 0 ? Math.round((n / assessedPages) * 100) : null);
  return {
    reportsUnevaluated,
    totalPages: stats.total_pages,
    assessedPages,
    unevaluatedPages,
    judgeOk: stats.judge_ok,
    operatorReview,
    judgeOkPct: pct(stats.judge_ok),
    operatorReviewPct: pct(operatorReview),
  };
}

/**
 * The assessed/unevaluated sentence, or "" for a bundle that predates the
 * counts (nothing is claimed either way).
 */
export function describeCleanQcAssessment(c: CleanQcCoverage): string {
  if (!c.reportsUnevaluated) return "";
  if (c.unevaluatedPages === 0) {
    return `All ${c.totalPages.toLocaleString("en-US")} pages were assessed.`;
  }
  return (
    `${c.assessedPages.toLocaleString("en-US")} pages assessed; ` +
    `${c.unevaluatedPages.toLocaleString("en-US")} could not be evaluated.`
  );
}
