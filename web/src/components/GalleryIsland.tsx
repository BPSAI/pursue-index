import { useEffect, useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";

interface Props {
  cards: CardMetadata[];
  base: string;
}

interface PostersIndex {
  posters: Record<string, string>;
  count: number;
}

type Filter = "all" | "image" | "video";

const FILTERS: { key: Filter; label: string; predicate: (c: CardMetadata) => boolean }[] = [
  { key: "all", label: "ALL", predicate: () => true },
  { key: "image", label: "IMAGES", predicate: (c) => c.asset_type === "IMG" },
  { key: "video", label: "VIDEOS", predicate: (c) => c.asset_type === "VID" },
];

/**
 * Year-bucket label for the tile's date stamp. Prefers `incident_date`
 * (when present and parseable) and falls back to `release_date`. The
 * manifest fields are free-form strings like "5/8/26" or "Late 2025"
 * so a strict Date parse would refuse most of them; we extract a 4-digit
 * year or a 2-digit year with a 19xx/20xx heuristic instead.
 */
function tileYear(c: CardMetadata): string {
  const sources = [c.incident_date, c.release_date].filter(Boolean) as string[];
  for (const s of sources) {
    // 4-digit year
    const m4 = s.match(/(\b19|20)\d{2}\b/);
    if (m4) return m4[0];
    // 2-digit year — pick up "26" → 2026, "47" → 1947, etc.
    const m2 = s.match(/\b(\d{2})\b/g);
    if (m2 && m2.length) {
      const last = m2[m2.length - 1];
      const n = parseInt(last, 10);
      if (!Number.isNaN(n)) {
        return n < 50 ? `20${last}` : `19${last}`;
      }
    }
  }
  return "—";
}

function GalleryTile({
  card,
  base,
  posterUrl,
}: {
  card: CardMetadata;
  base: string;
  posterUrl: string | null;
}) {
  const isImage = card.asset_type === "IMG";
  const isVideo = card.asset_type === "VID";
  const href = `${base}/card/${card.card_id}/`;
  const year = tileYear(card);
  return (
    <a
      href={href}
      class="group relative block border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 overflow-hidden hover:border-[color:var(--color-signal-cyan)] transition-colors"
      data-card-id={card.card_id}
      data-asset-type={card.asset_type}
    >
      <div class="aspect-[4/3] w-full bg-black/60 relative overflow-hidden">
        {isImage && card.modal_image_url ? (
          <img
            src={card.modal_image_url}
            alt={card.title}
            loading="lazy"
            class={`w-full h-full object-cover ${card.redacted ? "scanlines-soft" : ""}`}
          />
        ) : isVideo && posterUrl ? (
          <>
            <img
              src={posterUrl}
              alt={card.title}
              loading="lazy"
              class={`w-full h-full object-cover ${card.redacted ? "scanlines-soft" : ""}`}
            />
            {/* Play-triangle overlay so the tile reads as "video" at a glance even when the poster looks like a still image. */}
            <span
              aria-hidden="true"
              class="absolute inset-0 flex items-center justify-center pointer-events-none"
            >
              <svg
                width="40"
                height="40"
                viewBox="0 0 24 24"
                fill="rgba(0,0,0,0.55)"
                stroke="rgba(255,255,255,0.92)"
                stroke-width="1.5"
                stroke-linejoin="round"
              >
                <polygon points="6 4 20 12 6 20 6 4"></polygon>
              </svg>
            </span>
            <span class="absolute top-2 right-2 z-10 font-mono text-[9px] uppercase tracking-[0.2em] text-[color:var(--color-signal-violet)] bg-[color:var(--color-bg-deep)]/85 px-1.5 py-0.5 border border-[color:var(--color-signal-violet)]/40">
              VID
            </span>
          </>
        ) : isVideo ? (
          <div class="w-full h-full flex flex-col items-center justify-center text-[color:var(--color-text-dim)] gap-2 bg-[color:var(--color-bg-deep)]/85">
            <span class="font-mono text-[10px] tracking-[0.18em] uppercase text-[color:var(--color-signal-violet)]">
              VID
            </span>
            <svg
              aria-hidden="true"
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="text-[color:var(--color-signal-violet)] opacity-80"
            >
              <polygon points="6 4 20 12 6 20 6 4"></polygon>
            </svg>
            {card.dvids_video_id && (
              <span class="font-mono text-[9px] text-[color:var(--color-text-faint)] tracking-wide">
                DVIDS {card.dvids_video_id}
              </span>
            )}
          </div>
        ) : (
          <div class="w-full h-full flex items-center justify-center text-[color:var(--color-text-faint)] font-mono text-[10px]">
            (no preview)
          </div>
        )}
        {card.redacted && (
          <span class="absolute top-2 left-2 z-10 font-mono text-[9px] uppercase tracking-[0.2em] text-[color:var(--color-signal-red)] bg-[color:var(--color-bg-deep)]/85 px-1.5 py-0.5 border border-[color:var(--color-signal-red)]/40">
            REDACTED
          </span>
        )}
      </div>
      <div class="px-2 py-2 space-y-1 border-t border-[color:var(--color-border)]">
        <div class="flex items-center justify-between gap-2 font-mono text-[9px] uppercase tracking-[0.18em] text-[color:var(--color-text-faint)]">
          <span>{card.agency}</span>
          <span>{year}</span>
        </div>
        <p class="font-mono text-[11px] leading-snug text-[color:var(--color-text-bright)] line-clamp-2 break-words">
          {card.title}
        </p>
      </div>
    </a>
  );
}

export default function GalleryIsland({ cards, base }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [posters, setPosters] = useState<Record<string, string>>({});

  // Lazy-load the poster index. 404 is acceptable — VID tiles fall back
  // to the placeholder. The index is small (~25 entries × ~50 bytes).
  useEffect(() => {
    fetch(`${base}/data/video-posters/index.json`)
      .then((r) => (r.ok ? (r.json() as Promise<PostersIndex>) : null))
      .then((data) => {
        if (data?.posters) setPosters(data.posters);
      })
      .catch(() => {});
  }, [base]);

  const visible = useMemo(() => {
    const pred = FILTERS.find((f) => f.key === filter)?.predicate ?? (() => true);
    // Stable sort: images first, then by year desc (newest first), then by title.
    return [...cards].filter(pred).sort((a, b) => {
      const ay = parseInt(tileYear(a), 10) || 0;
      const by = parseInt(tileYear(b), 10) || 0;
      if (by !== ay) return by - ay;
      return a.title.localeCompare(b.title);
    });
  }, [cards, filter]);

  const counts = useMemo(() => {
    const out: Record<Filter, number> = { all: 0, image: 0, video: 0 };
    for (const c of cards) {
      out.all += 1;
      if (c.asset_type === "IMG") out.image += 1;
      if (c.asset_type === "VID") out.video += 1;
    }
    return out;
  }, [cards]);

  return (
    <div class="space-y-4">
      <div
        role="group"
        aria-label="Gallery asset-type filter"
        class="inline-flex font-mono text-[11px] uppercase tracking-[0.15em] border border-[color:var(--color-border)]"
      >
        {FILTERS.map((f, i) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            class={`px-3 py-1.5 transition-colors ${
              i > 0 ? "border-l border-[color:var(--color-border)]" : ""
            } ${
              filter === f.key
                ? "bg-[color:var(--color-bg-elevated)] text-[color:var(--color-signal-cyan)]"
                : "text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
            }`}
          >
            {f.label} <span class="text-[color:var(--color-text-faint)] ml-1 normal-case">{counts[f.key]}</span>
          </button>
        ))}
        <button
          type="button"
          aria-pressed={false}
          disabled
          title="Document thumbnails arrive in Phase 2 — page-1 PDF rendering pipeline"
          class="px-3 py-1.5 border-l border-[color:var(--color-border)] text-[color:var(--color-text-faint)] cursor-not-allowed opacity-60"
        >
          DOCUMENTS <span class="ml-1 normal-case">soon</span>
        </button>
      </div>

      <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-green)]">{visible.length}</span>{" "}
        TILE{visible.length === 1 ? "" : "S"}
      </div>

      {visible.length === 0 ? (
        <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
          <span class="text-[color:var(--color-signal-amber)]">[EMPTY]</span>
          <span class="ml-2">
            No cards match this filter in the current corpus.
          </span>
        </p>
      ) : (
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {visible.map((c) => (
            <GalleryTile
              key={c.card_id}
              card={c}
              base={base}
              posterUrl={
                c.asset_type === "VID" && posters[c.card_id]
                  ? `${base}/data/video-posters/${posters[c.card_id]}`
                  : null
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
