import { useEffect, useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";

interface Props {
  cards: CardMetadata[];
  base: string;
  /**
   * Allow-list of `card_id`s that are PDF-wrapped photographs (B001-
   * B024, FBI Composite Sketch, CENTCOM declass-header stills). The
   * IMAGES filter unions these with `asset_type === "IMG"` so users
   * looking for photographs find them all in one place. Empty array
   * = same behavior as the legacy IMG-only filter.
   * See scripts/build_photo_card_index.py for how the list is built.
   */
  photoPdfIds?: string[];
}

interface PostersIndex {
  posters: Record<string, string>;
  count: number;
}

interface ThumbsIndex {
  thumbs: Record<string, string>;
  count: number;
}

type Filter = "all" | "image" | "video" | "document";

/**
 * Build the FILTERS list, optionally extending the IMAGES predicate to
 * also match a known allow-list of PDF-wrapped photographs (B001-B024,
 * FBI Composite Sketch, CENTCOM declass-header stills). DOCUMENTS
 * still shows ALL `asset_type=PDF` cards including those photo-PDFs —
 * the filters are non-exclusive lenses, not partitions.
 */
function buildFilters(photoPdfIds: ReadonlySet<string>): {
  key: Filter; label: string; predicate: (c: CardMetadata) => boolean;
}[] {
  return [
    { key: "all", label: "ALL", predicate: () => true },
    {
      key: "image", label: "IMAGES",
      predicate: (c) => c.asset_type === "IMG" || photoPdfIds.has(c.card_id),
    },
    // Sprint 4f: AUD lumped with VID under "VIDEOS" lane — both are
    // DVIDS-hosted, no asset_url, no thumb. A separate "AUDIO" lane
    // would be UI noise at N=1 today; revisit if upstream adds more
    // audio cards.
    { key: "video", label: "VIDEOS", predicate: (c) => c.asset_type === "VID" || c.asset_type === "AUD" },
    { key: "document", label: "DOCUMENTS", predicate: (c) => c.asset_type === "PDF" },
  ];
}

/**
 * Build the alt-text for a gallery tile image. Upstream-curated
 * `image_alt_text` (added in tranche c9cc83fcaf43) is preferred when
 * present — it describes the image content directly ("Brown file
 * folder labeled with the number 78078.") rather than re-stating
 * the filename. Falls back to a structured per-asset-type string
 * derived from the card title.
 *
 * The "(contains redactions)" suffix is always appended for redacted
 * cards so screen-reader users get the same signal sighted users get
 * from the visible REDACTED corner badge.
 */
function imageAlt(card: CardMetadata, fallback: string): string {
  const base = card.image_alt_text || fallback;
  return card.redacted ? `${base} (contains redactions)` : base;
}

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
  thumbUrl,
}: {
  card: CardMetadata;
  base: string;
  posterUrl: string | null;
  thumbUrl: string | null;
}) {
  const isImage = card.asset_type === "IMG";
  // Sprint 4f: VID and AUD both render through the no-poster
  // DVIDS-embed shape since DVIDS-hosted audio doesn't ship a poster
  // image. ``isVideo`` keeps its name for diff-readability; the tile
  // label below uses ``card.asset_type`` so AUD shows up as AUD.
  const isVideo = card.asset_type === "VID" || card.asset_type === "AUD";
  const isAudio = card.asset_type === "AUD";
  const isPdf = card.asset_type === "PDF";
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
            alt={imageAlt(card, card.title)}
            loading="lazy"
            class={`w-full h-full object-cover ${card.redacted ? "scanlines-soft" : ""}`}
          />
        ) : isVideo && posterUrl ? (
          <>
            <img
              src={posterUrl}
              alt={imageAlt(card, `Video poster: ${card.title}`)}
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
            <span
              class={`font-mono text-[10px] tracking-[0.18em] uppercase ${isAudio ? "text-[color:var(--color-signal-amber)]" : "text-[color:var(--color-signal-violet)]"}`}
            >
              {card.asset_type}
            </span>
            {isAudio ? (
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
                class="text-[color:var(--color-signal-amber)] opacity-80"
              >
                <path d="M3 12h2l2-7 4 14 3-10 3 6h4"></path>
              </svg>
            ) : (
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
            )}
            {card.dvids_video_id && (
              <span class="font-mono text-[9px] text-[color:var(--color-text-faint)] tracking-wide">
                src: DVIDS {card.dvids_video_id}
              </span>
            )}
          </div>
        ) : isPdf && thumbUrl ? (
          <>
            <img
              src={thumbUrl}
              alt={imageAlt(card, `${card.title} — page 1 preview`)}
              loading="lazy"
              class={`w-full h-full object-cover ${card.redacted ? "scanlines-soft" : ""}`}
            />
            <span class="absolute top-2 right-2 z-10 font-mono text-[9px] uppercase tracking-[0.2em] text-[color:var(--color-signal-cyan)] bg-[color:var(--color-bg-deep)]/85 px-1.5 py-0.5 border border-[color:var(--color-signal-cyan)]/40">
              PDF
            </span>
          </>
        ) : isPdf ? (
          <div class="w-full h-full flex flex-col items-center justify-center text-[color:var(--color-text-dim)] gap-2 bg-[color:var(--color-bg-deep)]/85">
            <span class="font-mono text-[10px] tracking-[0.18em] uppercase text-[color:var(--color-signal-cyan)]">
              PDF
            </span>
            <svg
              aria-hidden="true"
              width="28"
              height="28"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="text-[color:var(--color-signal-cyan)] opacity-70"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
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

export default function GalleryIsland({ cards, base, photoPdfIds = [] }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [posters, setPosters] = useState<Record<string, string>>({});
  const [thumbs, setThumbs] = useState<Record<string, string>>({});

  const photoPdfSet = useMemo(() => new Set(photoPdfIds), [photoPdfIds]);
  const FILTERS_LIVE = useMemo(() => buildFilters(photoPdfSet), [photoPdfSet]);

  // Lazy-load the poster + thumb indexes. 404 on either is acceptable
  // — tiles fall back to the placeholder. Each index is small
  // (~25 entries × ~50 bytes for posters; ~116 entries × ~50 bytes
  // for thumbs). Two parallel fetches; no dependency between them.
  useEffect(() => {
    fetch(`${base}/data/video-posters/index.json`)
      .then((r) => (r.ok ? (r.json() as Promise<PostersIndex>) : null))
      .then((data) => {
        if (data?.posters) setPosters(data.posters);
      })
      .catch(() => {});
    fetch(`${base}/data/thumbs/index.json`)
      .then((r) => (r.ok ? (r.json() as Promise<ThumbsIndex>) : null))
      .then((data) => {
        if (data?.thumbs) setThumbs(data.thumbs);
      })
      .catch(() => {});
  }, [base]);

  const visible = useMemo(() => {
    const pred = FILTERS_LIVE.find((f) => f.key === filter)?.predicate ?? (() => true);
    // Stable sort: images first, then by year desc (newest first), then by title.
    return [...cards].filter(pred).sort((a, b) => {
      const ay = parseInt(tileYear(a), 10) || 0;
      const by = parseInt(tileYear(b), 10) || 0;
      if (by !== ay) return by - ay;
      return a.title.localeCompare(b.title);
    });
  }, [cards, filter, FILTERS_LIVE]);

  const counts = useMemo(() => {
    const out: Record<Filter, number> = { all: 0, image: 0, video: 0, document: 0 };
    for (const c of cards) {
      out.all += 1;
      // IMAGES count unions `asset_type=IMG` with the photo-PDF
      // allow-list so the badge matches what the filter actually
      // surfaces. Without this, the badge would say "14" but clicking
      // through would render 40 tiles — user-confusing.
      if (c.asset_type === "IMG" || photoPdfSet.has(c.card_id)) out.image += 1;
      // Sprint 4f: AUD counts toward the VIDEOS lane (DVIDS-hosted,
      // no asset_url, mirrors VID behavior).
      if (c.asset_type === "VID" || c.asset_type === "AUD") out.video += 1;
      if (c.asset_type === "PDF") out.document += 1;
    }
    return out;
  }, [cards, photoPdfSet]);

  return (
    <div class="space-y-4">
      <div
        role="group"
        aria-label="Gallery asset-type filter"
        class="inline-flex font-mono text-[11px] uppercase tracking-[0.15em] border border-[color:var(--color-border)]"
      >
        {FILTERS_LIVE.map((f, i) => (
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
      </div>

      <div
        aria-live="polite"
        aria-atomic="true"
        class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]"
      >
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
              thumbUrl={
                c.asset_type === "PDF" && thumbs[c.card_id]
                  ? `${base}/data/thumbs/${thumbs[c.card_id]}`
                  : null
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
