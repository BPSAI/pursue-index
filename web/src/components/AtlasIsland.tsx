import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  AGENCY_ORDER,
  agencyToCategory,
  categoryColors,
  filterIndicesByQuery,
  kmeansClusters,
  pointToScatterplotRow,
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
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [width, setWidth] = useState(
    typeof window === "undefined" ? 1024 : window.innerWidth,
  );
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

  // Track viewport width for the mobile-fallback decision.
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Build a docs lookup keyed by ``card_id-page`` so we can resolve a
  // hovered point to its title + snippet without scanning the array.
  const docsByKey = useMemo(() => {
    const m = new Map<string, PageDoc>();
    for (const d of docs) m.set(`${d.card_id}-${d.page}`, d);
    return m;
  }, [docs]);

  const pointsForRender = useMemo(() => layout?.points ?? [], [layout]);
  const isMobile = width > 0 && width < MOBILE_BREAKPOINT;

  // Lazy-load regl-scatterplot only when ready + on desktop. Avoids
  // pulling the WebGL bundle into the SSR'd HTML and into the mobile
  // fallback path.
  useEffect(() => {
    if (status !== "ready" || isMobile || !canvasRef.current || !layout) return;
    let cancelled = false;
    let scatterplot: {
      draw: (rows: number[][]) => Promise<void>;
      set: (props: Record<string, unknown>) => Promise<void>;
      destroy: () => void;
      subscribe: (event: string, handler: (info: unknown) => void) => void;
    } | null = null;
    void import("regl-scatterplot").then((mod) => {
      if (cancelled || !canvasRef.current) return;
      const createScatterplot = (mod as { default: (opts: unknown) => unknown })
        .default;
      const canvas = canvasRef.current;
      const rect = canvas.getBoundingClientRect();
      scatterplot = createScatterplot({
        canvas,
        width: rect.width,
        height: rect.height,
        pointColor: categoryColors().map(([r, g, b, a]) => [r, g, b, a]),
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
            window.location.href = `${base}/card/${p.card_id}?page=${p.page}#page-${p.page}`;
          }
        }
      });
      const rows = layout.points.map(pointToScatterplotRow);
      void scatterplot.draw(rows);
      scatterplotRef.current = scatterplot;
    });
    return () => {
      cancelled = true;
      if (scatterplotRef.current) {
        scatterplotRef.current.destroy();
        scatterplotRef.current = null;
      }
    };
    // base + layout + isMobile are the meaningful dep set; ESLint would
    // also list `status` but it's tracked above with a guard.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, isMobile, layout, base]);

  // Re-color on query change: matched indices keep full opacity, others
  // dim. The cheapest way is a fresh draw with a new fourth-column
  // (opacity-ish) value per row.
  useEffect(() => {
    const sp = scatterplotRef.current;
    if (!sp || !layout) return;
    const matched = new Set(
      filterIndicesByQuery(layout.points, query, (p) => {
        const d = docsByKey.get(`${p.card_id}-${p.page}`);
        return `${d?.title ?? ""} ${d?.text ?? ""}`;
      }),
    );
    const rows = layout.points.map((p, i): number[] => [
      p.x,
      p.y,
      agencyToCategory(p.agency),
      matched.has(i) ? 1.0 : 0.15,
    ]);
    void sp.draw(rows);
  }, [query, layout, docsByKey]);

  if (status === "loading") {
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
        <ClusterListFallback points={pointsForRender} docsByKey={docsByKey} base={base} />
      ) : (
        <div class="relative border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/80 aspect-[4/3] sm:aspect-[16/10]">
          <canvas ref={canvasRef} class="block w-full h-full" />
          <AtlasLegend />
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
}: {
  points: AtlasPoint[];
  docsByKey: Map<string, PageDoc>;
  base: string;
}) {
  // 8 clusters keeps the list scannable without losing density signal —
  // matches the plan's k=8 default.
  const labels = useMemo(() => kmeansClusters(points, 8, 42), [points]);
  const clusters = useMemo(() => groupByCluster(points, labels), [points, labels]);
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
                    href={`${base}/card/${p.card_id}?page=${p.page}#page-${p.page}`}
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
): { cluster: number; points: AtlasPoint[]; dominantAgency: string }[] {
  const groups = new Map<number, AtlasPoint[]>();
  for (let i = 0; i < points.length; i++) {
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
