import { useRef, useState } from "preact/hooks";
import { buildSearchHref } from "./homepage-search.ts";

/**
 * Homepage hero search-shortcut island.
 *
 * Replaces the prior `<SearchIsland client:load>` on `/` which eagerly
 * fetched the 7.1 MB pages.json + built a MiniSearch index of ~4,127
 * docs on every homepage visit. That fetch was the LCP-path asset in
 * APAC + Finland (no CF edge cache fill on cold regions) AND the
 * dominant TBT contributor (MiniSearch index build is sync).
 *
 * This island intentionally does NOT load `/data/pages.json`, does NOT
 * import MiniSearch, and is small enough to ship via `client:idle`.
 * On submit it redirects to `/search?q=<query>` and lets the search
 * route pay the hydration cost honestly.
 *
 * Sprint 2 perf-pass — see `docs/perf-baseline.md`.
 */
interface Props {
  base: string;
  examples?: readonly string[];
}

export default function HomepageSearch({ base, examples }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit(event: Event) {
    event.preventDefault();
    window.location.href = buildSearchHref(base, query);
  }

  // The form's `action` is the same target as `buildSearchHref` builds
  // for an empty query. Combined with `name="q"` on the input and
  // `method="get"`, a pre-hydration submit (user types + hits Enter
  // before `client:idle` fires) still works correctly: the browser
  // does a native GET to `${base}/search?q=<query>`. Once the island
  // hydrates, our JS handler takes over and gets the same destination
  // via `buildSearchHref` (centralised encoding rules).
  const formAction = `${base.replace(/\/$/, "")}/search`;

  return (
    <form
      onSubmit={handleSubmit}
      action={formAction}
      method="get"
      class="space-y-3"
    >
      <div class="relative">
        <input
          ref={inputRef}
          type="search"
          name="q"
          value={query}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          placeholder="search the corpus…"
          class="w-full pr-16"
          aria-label="Search the PURSUE corpus"
          autofocus
        />
        <kbd
          aria-hidden="true"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[color:var(--color-text-faint)] border border-[color:var(--color-border)] px-1.5 py-0.5 rounded-sm pointer-events-none"
        >
          ↵
        </kbd>
      </div>
      <p class="text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-text-faint)]">/search</span>
        <span aria-hidden="true" class="mx-2 text-[color:var(--color-text-faint)]">|</span>
        ENTER TO QUERY
      </p>
      {examples && examples.length > 0 && (
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[10px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-faint)]">
            try:
          </span>
          {examples.map((ex) => (
            <button
              type="button"
              onClick={() => {
                setQuery(ex);
                inputRef.current?.focus();
              }}
              class="px-2 py-1 text-[11px] font-mono border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-signal-green)]/60 hover:text-[color:var(--color-signal-green)] transition-colors"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
