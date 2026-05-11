import CardReaderView from "./CardReaderView.tsx";
import {
  filterCleanedPages,
  requiresUiNotice,
  type CleanedPayload,
} from "./cleaned-pages.ts";

export type CleanedStatus = "idle" | "loading" | "loaded" | "missing" | "error";

interface Props {
  cardId: string;
  status: CleanedStatus;
  payload: CleanedPayload | null;
  initialPage: number | null;
  assetUrl?: string | null;
  onSwitchToRaw: () => void;
}

/**
 * Cleaned-mode view: lazy-loaded LLM-cleaned reading text overlay.
 *
 * Reuses the Reader-mode prose typography (so paragraph reflow and
 * search-result highlighting stay consistent) and pins a per-page
 * attribution footer below the article: "Cleaned by <model_id> · raw
 * transcript →". No inline markers in the rendered text (those would
 * contaminate copy-paste citations) — the rendered text is purely the
 * cleaned text, with provenance metadata available in the JSON payload
 * for downstream citation tooling.
 *
 * Soft-fallback states:
 *   - status="loading"  : "LOADING CLEANED TEXT…"
 *   - status="missing"  : pilot mirror not yet published
 *   - empty page list   : pilot didn't cover this card
 *
 * Never silently falls back to Raw and mislabels it — the contract is
 * to tell the user what they're looking at.
 */
export default function CardCleanedView({
  cardId,
  status,
  payload,
  initialPage,
  assetUrl,
  onSwitchToRaw,
}: Props) {
  if (status === "loading" || status === "idle") {
    return (
      <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
        LOADING CLEANED TEXT<span class="pi-caret"></span>
      </p>
    );
  }
  if (status === "missing" || status === "error") {
    return (
      <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-amber)]">[CLEANED PENDING]</span>
        <span class="ml-2">
          Cleaned text mirror not yet published. View Raw or Reader.
        </span>
      </p>
    );
  }
  const cleanedPages = filterCleanedPages(payload, cardId);
  if (cleanedPages.length === 0) {
    return (
      <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-amber)]">[NOT IN PILOT]</span>
        <span class="ml-2">
          Cleaned text not yet available for this card — view Raw or Reader.
        </span>
      </p>
    );
  }
  // vaivora P2 #3: align fallback to the canonical date-suffixed model
  // id used in clean_cli.py and methodology.astro. Without the suffix
  // the citation footer breaks reproducibility hygiene if payload meta
  // is ever missing.
  const modelId = payload?.meta.model_id ?? "claude-haiku-4-5-20251001";
  return (
    <div class="space-y-3">
      <CardReaderView
        pages={cleanedPages.map((p) => ({
          page: p.page,
          text: p.text,
          // vaivora P0 fix: forward the skip reason so the reader
          // renders the appropriate notice instead of falling through
          // to the generic `[BLANK]` message. Gated via
          // `requiresUiNotice` so both `length_divergence` and
          // `content_filter` route through CardReaderView's
          // cleanup-notice branch (the latter is the third skip
          // reason — added after Anthropic's content-moderation policy
          // declined output for charged source material in the pilot).
          // `empty_input` intentionally stays undefined so it routes
          // to the [BLANK] branch (consistent with how Raw renders
          // blank pages). A future fourth reason is a one-line opt-in
          // on the `requiresUiNotice` predicate in `cleaned-pages.ts`.
          ...(requiresUiNotice(p.cleanup_skipped)
            ? { cleanupSkipped: p.cleanup_skipped }
            : {}),
        }))}
        initialPage={initialPage}
        assetUrl={assetUrl}
        onSwitchToRaw={onSwitchToRaw}
      />
      <p
        data-pi-cleaned-attribution="true"
        class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] text-center pt-2 border-t border-[color:var(--color-border)]"
      >
        Cleaned by {modelId} ·{" "}
        <button
          type="button"
          onClick={onSwitchToRaw}
          class="underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)] hover:text-[color:var(--color-signal-cyan)] normal-case tracking-normal"
        >
          raw transcript →
        </button>
      </p>
    </div>
  );
}
