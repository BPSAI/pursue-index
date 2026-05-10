import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  AGENCY_ORDER,
  agencyToCategory,
  buildAtlasMiniSearch,
  buildCardHref,
  categoryColors,
  kmeansClusters,
  pointToScatterplotRow,
  searchIndicesViaMiniSearch,
  type AtlasMiniSearch,
  type AtlasPoint,
} from "./atlas-helpers.ts";

/**
 * 2D semantic browser for the PURSUE corpus.
 *
 * Lazy-loads ``/data/atlas-layout.json`` (UMAP coords + agency) and
 * ``/data/pages.json`` (snippets + search) on hydration. Renders via
 * regl-scatterplot (WebGL) for pan/zoom/lasso at 4k+ points; falls
 * back to a list view of k-means clusters at viewports < 400px.
 *
 * The component is deliberately small: pure functions live in
 * ``./atlas-helpers.ts``, and the regl wiring is loaded dynamically
 * so visitors who never hit ``/atlas`` don't pay for the ~50 KB
 * gzipped scatterplot bundle.
 */

interface PageDoc {
  id: string;
  card_id: string;
  page: number;
  title: string;
  text: string;
}

interface Layout {
  model_id: string;
  n: number;
  points: AtlasPoint[];
  augmented_by?: { dataset?: string; revision?: string; sha256?: string };
}

interface Props {
  base: string;
}

type Status = "loading" | "missing" | "ready" | "error";

const MOBILE_BREAKPOINT = 400;
const TOOLTIP_SNIPPET_LEN = 180;

export default function AtlasIsland({ base }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [layout, setLayout] = useState<Layout | null>(null);
  const [docs, setDocs] = useState<PageDoc[]>([]);
  const [query, setQuery] = useState("");
  // Debounced query feeds the (expensive) full-array re-upload effect
  // — typing "blue book" shouldn't fire 9 redraws of 4,119 rows. The
  // input element keeps using ``query`` for instant input feedback;
  // the scatterplot re-draw watches ``debouncedQuery`` only.
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  // Defensive: surface canvas-mount failures (CSP block, missing WebGL,
  // failed dynamic import, regl init throw) instead of leaving the user
  // staring at an empty bordered box. Distinct from the data-fetch
  // ``status === "error"`` path — that one fires before mount; this one
  // fires during/after the regl-scatterplot import + init.
  const [mountError, setMountError] = useState<string | null>(null);
  // Start at 0 (unknown) and let the mount effect set the real width.
  // SSR'ing 1024 would flash the desktop canvas-mount path on a real
  // <400px viewport before the first resize event corrects it (nayru #6).
  const [width, setWidth] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scatterplotRef = useRef<{
    draw: (rows: number[][]) => Promise<void>;
    set: (props: Record<string, unknown>) => Promise<void>;
    destroy: () => void;
  } | null>(null);

  // Load layout + pages.json in parallel — the scatterplot can render
  // before docs land (just no snippet tooltips), but we wait for both
  // before flipping to "ready" so the search box doesn't appear empty.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(`${base}/data/atlas-layout.json`).then(async (r) => {
        if (!r.ok) throw new Error(`atlas-layout: ${r.status}`);
        return (await r.json()) as Layout;
      }),
      fetch(`${base}/data/pages.json`).then(async (r) => {
        if (!r.ok) throw new Error(`pages: ${r.status}`);
        return (await r.json()) as PageDoc[];
      }),
    ])
      .then(([l, d]) => {
        if (cancelled) return;
        setLayout(l);
        setDocs(d);
        setStatus("ready");
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) setStatus(err.message?.includes("404") ? "missing" : "error");
      });
    return () => {
      cancelled = true;
    };
  }, [base]);

  // Track viewport width for the mobile-fallback decision. The initial
  // setWidth call here is what flips the component out of the "width=0"
  // hold state — that hold prevents a brief desktop-canvas mount on
  // real <400px viewports (the prior code SSR'd 1024 unconditionally).
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Debounce ``query`` -> ``debouncedQuery`` at 150ms. Without this,
  // each keystroke triggers a full 4,119-row re-upload through the
  // re-color effect below. 150ms is the SearchIsland-feels-instant
  // budget; lower starts to jank on lower-end mobile/tablets.
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), 150);
    return () => clearTimeout(handle);
  }, [query]);

  // Push width changes into the regl-scatterplot instance — without
  // this, a desktop window resize leaves the WebGL viewport stretched
  // and hit-testing offset (Codex-1). regl-scatterplot's docs require
  // explicit ``set({width, height})`` on canvas resize.
  useEffect(() => {
    const sp = scatterplotRef.current;
    if (!sp || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      void sp.set({ width: rect.width, height: rect.height });
    }
  }, [width]);

  // Build a docs lookup keyed by ``card_id-page`` so we can resolve a
  // hovered point to its title + snippet without scanning the array.
  const docsByKey = useMemo(() => {
    const m = new Map<string, PageDoc>();
    for (const d of docs) m.set(`${d.card_id}-${d.page}`, d);
    return m;
  }, [docs]);

  const pointsForRender = useMemo(() => layout?.points ?? [], [layout]);
  // Canvas mount requires a measured viewport >= 400px. ``width === 0``
  // is the pre-mount state — neither path renders until the resize
  // effect runs and sets the real width. ``isMobile`` is true for
  // measured-and-narrow only.
  const hasMeasuredViewport = width > 0;
  const isMobile = hasMeasuredViewport && width < MOBILE_BREAKPOINT;

  // Build the MiniSearch index once when docs land. Re-runs only when
  // points or doc set changes — keystrokes hit the cached index, not a
  // fresh build. Replaces the naive substring filter so /atlas search
  // lights up the same set of rows /search does for the same input
  // (vaivora P1).
  const atlasIndex = useMemo<AtlasMiniSearch | null>(() => {
    if (!layout) return null;
    return buildAtlasMiniSearch(layout.points, (p) =>
      docsByKey.get(`${p.card_id}-${p.page}`),
    );
  }, [layout, docsByKey]);

  // Lazy-load regl-scatterplot only when ready + on a measured desktop
  // viewport. Avoids pulling the WebGL bundle into the SSR'd HTML, into
  // the mobile fallback path, AND into the brief width=0 hold state
  // before the resize effect has run (which would otherwise flash a
  // canvas-mount on real <400px viewports — nayru #6).
  useEffect(() => {
    if (status !== "ready" || !hasMeasuredViewport || isMobile || !canvasRef.current || !layout) return;
    let cancelled = false;
    let scatterplot: {
      draw: (rows: number[][]) => Promise<void>;
      set: (props: Record<string, unknown>) => Promise<void>;
      destroy: () => void;
      subscribe: (event: string, handler: (info: unknown) => void) => void;
    } | null = null;
    void import("regl-scatterplot")
      .then(async (mod) => {
        if (cancelled || !canvasRef.current) return;
        const createScatterplot = (mod as { default: (opts: unknown) => unknown })
          .default;
        const canvas = canvasRef.current;
        const rect = canvas.getBoundingClientRect();
        scatterplot = createScatterplot({
          canvas,
          width: rect.width,
          height: rect.height,
          pointColor: categoryColors(),
          pointSize: 4,
          backgroundColor: [10 / 255, 13 / 255, 18 / 255, 1],
        }) as typeof scatterplot;
        if (!scatterplot) return;
        scatterplot.subscribe("pointOver", (info) => {
          if (typeof info === "number") setHoverIdx(info);
        });
        scatterplot.subscribe("pointOut", () => setHoverIdx(null));
        scatterplot.subscribe("select", (info) => {
          const sel = (info as { points?: number[] })?.points;
          if (sel && sel.length > 0) {
            const p = layout.points[sel[0]];
            if (p) {
              window.location.href = buildCardHref(base, p.card_id, p.page);
            }
          }
        });
        const rows = layout.points.map(pointToScatterplotRow);
        // Awaited so an async failure inside `draw()` (rare — late shader
        // compile error, GPU buffer upload reject) propagates into the
        // outer `.catch` and triggers the mount-error overlay. A bare
        // `void scatterplot.draw(rows)` would discard the rejection and
        // leave the user staring at an empty bordered box (nayru P1 #2).
        await scatterplot.draw(rows);
        scatterplotRef.current = scatterplot;
      })
      .catch((err) => {
        // CSP blocks (e.g. missing 'unsafe-eval' for regl shader compile),
        // WebGL-unavailable browsers, or chunked-import failures end up
        // here. Surface a visible message inside the canvas frame so the
        // page degrades gracefully instead of showing an empty box.
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.error("[AtlasIsland] regl-scatterplot mount failed:", err);
        setMountError(
          err instanceof Error && err.message ? err.message : "unknown error",
        );
      });
    return () => {
      cancelled = true;
      if (scatterplotRef.current) {
        scatterplotRef.current.destroy();
        scatterplotRef.current = null;
      }
    };
    // base + layout + isMobile + hasMeasuredViewport are the meaningful dep set;
    // ESLint would also list `status` but it's tracked above with a guard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, hasMeasuredViewport, isMobile, layout, base]);

  // Re-color on (debounced) query change: matched indices keep full
  // opacity, others dim. The cheapest way is a fresh draw with a new
  // fourth-column (opacity-ish) value per row. Driven off
  // ``debouncedQuery`` so each keystroke doesn't re-upload 4,119 rows
  // (nayru #5). Search is via the MiniSearch index for parity with
  // /search (vaivora P1).
  useEffect(() => {
    const sp = scatterplotRef.current;
    if (!sp || !layout || !atlasIndex) return;
    const matched = new Set(
      searchIndicesViaMiniSearch(atlasIndex, debouncedQuery),
    );
    const rows = layout.points.map((p, i): number[] => [
      p.x,
      p.y,
      agencyToCategory(p.agency),
      matched.has(i) ? 1.0 : 0.15,
    ]);
    void sp.draw(rows);
  }, [debouncedQuery, layout, atlasIndex]);

  if (status === "loading" || !hasMeasuredViewport) {
    // The width=0 hold prevents a desktop-canvas flash on real <400px
    // viewports — render the loading state until the resize effect
    // has measured the viewport.
    return <p class="pi-loading text-xs">DECLASSIFYING<span class="pi-caret"></span></p>;
  }
  if (status === "missing") {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-amber)]">
        [LAYOUT PENDING] /data/atlas-layout.json not yet published.
      </p>
    );
  }
  if (status === "error" || !layout) {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-red)]">
        [ERR] Failed to load atlas layout.
      </p>
    );
  }

  return (
    <div class="space-y-4">
      <div>
        <input
          type="search"
          value={query}
          onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
          placeholder={`search ${layout.n.toLocaleString()} pages — matches glow, others dim`}
          class="w-full"
          aria-label="Filter atlas points by search query"
        />
        <p class="mt-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-green)]">{layout.n.toLocaleString()}</span>
          <span class="mx-1 text-[color:var(--color-text-faint)]">·</span>
          PAGES PROJECTED · UMAP r_state=42
        </p>
      </div>
      {isMobile ? (
        <ClusterListFallback
          points={pointsForRender}
          docsByKey={docsByKey}
          base={base}
          atlasIndex={atlasIndex}
          query={debouncedQuery}
        />
      ) : (
        <div class="relative border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/80 aspect-[4/3] sm:aspect-[16/10]">
          <canvas ref={canvasRef} class="block w-full h-full" />
          <AtlasLegend />
          {mountError !== null && (
            // Fully opaque so a half-rendered canvas behind doesn't bleed
            // through (nayru P2 #5). Using `bg-deep` (no /90 alpha) keeps
            // the overlay readable regardless of canvas state at the
            // moment of failure.
            <div class="absolute inset-0 flex items-center justify-center p-4 text-center bg-[color:var(--color-bg-deep)]">
              <p class="font-mono text-sm text-[color:var(--color-signal-red)] max-w-md leading-relaxed">
                [ATLAS UNAVAILABLE] WebGL initialization failed in this browser.
                <span class="block mt-1 text-[11px] text-[color:var(--color-text-dim)] uppercase tracking-[0.15em]">
                  see browser console for details
                </span>
              </p>
            </div>
          )}
          {hoverIdx !== null && layout.points[hoverIdx] && (
            <Tooltip point={layout.points[hoverIdx]} doc={docsByKey.get(`${layout.points[hoverIdx].card_id}-${layout.points[hoverIdx].page}`)} />
          )}
        </div>
      )}
      <p class="text-[11px] font-mono text-[color:var(--color-text-dim)] leading-relaxed max-w-3xl">
        Dots are a 2D approximation, not ground-truth topic groupings —
        the layout depends on the UMAP seed and shifts when retuned.
        See <a href={`${base}/methodology#atlas`} class="text-[color:var(--color-signal-cyan)] underline">methodology</a> for projection details.
      </p>
    </div>
  );
}

function AtlasLegend() {
  const colors = categoryColors();
  const labels = [...AGENCY_ORDER, "UNKNOWN"];
  return (
    <ul class="absolute top-2 right-2 bg-[color:var(--color-bg-deep)]/85 border border-[color:var(--color-border)] p-2 text-[10px] font-mono uppercase tracking-[0.15em] space-y-1 pointer-events-none">
      {labels.map((label, i) => {
        const [r, g, b] = colors[i];
        const swatch = `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
        return (
          <li class="flex items-center gap-2">
            <span class="size-2 inline-block" style={{ background: swatch }}></span>
            <span class="text-[color:var(--color-text-dim)]">{label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Tooltip({ point, doc }: { point: AtlasPoint; doc: PageDoc | undefined }) {
  const snippet = doc?.text ? doc.text.slice(0, TOOLTIP_SNIPPET_LEN) : "";
  return (
    <div class="absolute bottom-2 left-2 max-w-md bg-[color:var(--color-bg-deep)]/95 border border-[color:var(--color-signal-green)]/60 p-2 font-mono text-[11px] pointer-events-none">
      <div class="text-[color:var(--color-signal-cyan)]">
        {point.card_id.slice(0, 8)} · P{point.page}
      </div>
      {doc?.title && (
        <div class="text-[color:var(--color-text-bright)] line-clamp-1 mt-0.5">{doc.title}</div>
      )}
      {snippet && (
        <p class="text-[color:var(--color-text-dim)] line-clamp-2 mt-1 leading-snug">{snippet}</p>
      )}
      <div class="text-[10px] text-[color:var(--color-text-faint)] mt-1 uppercase tracking-[0.15em]">
        click to open
      </div>
    </div>
  );
}

function ClusterListFallback({
  points,
  docsByKey,
  base,
  atlasIndex,
  query,
}: {
  points: AtlasPoint[];
  docsByKey: Map<string, PageDoc>;
  base: string;
  atlasIndex: AtlasMiniSearch | null;
  query: string;
}) {
  // 8 clusters keeps the list scannable without losing density signal —
  // matches the plan's k=8 default. Built from the full point set so
  // cluster labels stay stable while the user types.
  const labels = useMemo(() => kmeansClusters(points, 8, 42), [points]);
  // Filter the cluster contents by the active query (Codex-2 — without
  // this, the search input on phones / <400px viewports has no effect).
  // Empty query means "show everything" by MiniSearch contract.
  const matched = useMemo(() => {
    if (!atlasIndex) return null;
    return new Set(searchIndicesViaMiniSearch(atlasIndex, query));
  }, [atlasIndex, query]);
  const clusters = useMemo(
    () => groupByCluster(points, labels, matched),
    [points, labels, matched],
  );
  return (
    <ul class="space-y-3">
      {clusters.map((c) => (
        <li class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-3">
          <div class="text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-signal-green)]">
            ▸ cluster · {c.dominantAgency} ({c.points.length} pages)
          </div>
          <ul class="mt-2 space-y-1 text-[12px]">
            {c.points.slice(0, 5).map((p) => {
              const d = docsByKey.get(`${p.card_id}-${p.page}`);
              return (
                <li>
                  <a
                    href={buildCardHref(base, p.card_id, p.page)}
                    class="text-[color:var(--color-text-bright)] hover:text-[color:var(--color-signal-green)]"
                  >
                    {d?.title ?? p.card_id} · P{p.page}
                  </a>
                </li>
              );
            })}
            {c.points.length > 5 && (
              <li class="text-[color:var(--color-text-faint)] text-[11px] font-mono">
                + {c.points.length - 5} more
              </li>
            )}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function groupByCluster(
  points: AtlasPoint[],
  labels: number[],
  matched: Set<number> | null,
): { cluster: number; points: AtlasPoint[]; dominantAgency: string }[] {
  const groups = new Map<number, AtlasPoint[]>();
  for (let i = 0; i < points.length; i++) {
    if (matched && !matched.has(i)) continue;
    const arr = groups.get(labels[i]) ?? [];
    arr.push(points[i]);
    groups.set(labels[i], arr);
  }
  const out: { cluster: number; points: AtlasPoint[]; dominantAgency: string }[] = [];
  for (const [cluster, pts] of groups.entries()) {
    const counts = new Map<string, number>();
    for (const p of pts) counts.set(p.agency, (counts.get(p.agency) ?? 0) + 1);
    let dominant = "UNKNOWN";
    let max = 0;
    for (const [a, n] of counts) if (n > max) {
      dominant = a;
      max = n;
    }
    out.push({ cluster, points: pts, dominantAgency: dominant });
  }
  out.sort((a, b) => b.points.length - a.points.length);
  return out;
}
