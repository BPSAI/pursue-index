import { useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";

/**
 * Screen-reader / keyboard accessible alternative to the regl-scatterplot
 * canvas on /atlas.
 *
 * The plan (`.paircoder/plans/accessibility-audit-and-remediation.md`,
 * § "/atlas accessible alternative") calls for a parallel surface — not
 * a retrofit of the canvas itself — that shares the same data origin as
 * the visualization and is reachable on every viewport (NOT mobile-only).
 *
 * This component renders the corpus as a sortable HTML table with
 * `aria-sort` on column headers. Each row links to /card/<card_id>, the
 * same destination clicking a dot in the canvas would produce. Search
 * is a plain accessible input that filters rows by title/agency/date —
 * deliberately simpler than the canvas search (which uses MiniSearch
 * over per-page OCR text); the table is a navigation surface, not a
 * full-text retrieval one. For full-text search, /search remains the
 * dedicated route.
 *
 * Two views — "browse by agency" and "browse by date" — are exposed via
 * a toggle. Both render the same table; the toggle just changes the
 * default sort. (The user can re-sort either view by any column.)
 */

interface Props {
  cards: CardMetadata[];
  base: string;
}

type SortKey = "title" | "agency" | "asset_type" | "incident_date" | "release_date";
type SortDir = "asc" | "desc";

// Empty-string treated as "—" in display and pushed to the end on asc sort.
function cmp(a: string | null | undefined, b: string | null | undefined, dir: SortDir): number {
  const av = a ?? "";
  const bv = b ?? "";
  // Empty values always sort to the end regardless of direction so the
  // table doesn't lead with rows of "— — —" in either order.
  if (av === "" && bv !== "") return 1;
  if (bv === "" && av !== "") return -1;
  const r = av.localeCompare(bv);
  return dir === "asc" ? r : -r;
}

function getSortValue(c: CardMetadata, key: SortKey): string | null {
  switch (key) {
    case "title":
      return c.title;
    case "agency":
      return c.agency;
    case "asset_type":
      return c.asset_type;
    case "incident_date":
      return c.incident_date;
    case "release_date":
      return c.release_date;
  }
}

function ariaSortValue(active: boolean, dir: SortDir): "ascending" | "descending" | "none" {
  if (!active) return "none";
  return dir === "asc" ? "ascending" : "descending";
}

interface ColumnDef {
  key: SortKey;
  label: string;
  thClass: string;
  /** Render the cell value; receives the row card so dates etc. can be
      formatted independently from the sort key. */
  render: (c: CardMetadata) => preact.ComponentChildren;
}

const COLUMNS: ColumnDef[] = [
  {
    key: "title",
    label: "Title",
    thClass: "min-w-[16rem]",
    render: (c) => c.title,
  },
  {
    key: "agency",
    label: "Agency",
    thClass: "",
    render: (c) => c.agency,
  },
  {
    key: "asset_type",
    label: "Type",
    thClass: "",
    render: (c) => c.asset_type,
  },
  {
    key: "incident_date",
    label: "Incident",
    thClass: "",
    render: (c) => c.incident_date ?? "—",
  },
  {
    key: "release_date",
    label: "Released",
    thClass: "",
    render: (c) => c.release_date ?? "—",
  },
];

export default function AtlasAccessibleBrowser({ cards, base }: Props) {
  const [view, setView] = useState<"agency" | "date">("agency");
  const [sortKey, setSortKey] = useState<SortKey>("agency");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filter, setFilter] = useState("");
  const [redactedOnly, setRedactedOnly] = useState(false);

  // Switching view resets the sort to the natural anchor for that view
  // (agency view → sort by agency; date view → sort by incident date desc).
  const setViewAndSort = (v: "agency" | "date") => {
    setView(v);
    if (v === "agency") {
      setSortKey("agency");
      setSortDir("asc");
    } else {
      setSortKey("incident_date");
      setSortDir("desc");
    }
  };

  const onHeaderClick = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(k);
      setSortDir("asc");
    }
  };

  const visibleRows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    let rows = cards;
    if (redactedOnly) rows = rows.filter((c) => c.redacted);
    if (q) {
      rows = rows.filter(
        (c) =>
          c.title.toLowerCase().includes(q) ||
          c.agency.toLowerCase().includes(q) ||
          (c.incident_location ?? "").toLowerCase().includes(q),
      );
    }
    return [...rows].sort((a, b) =>
      cmp(getSortValue(a, sortKey), getSortValue(b, sortKey), sortDir),
    );
  }, [cards, filter, redactedOnly, sortKey, sortDir]);

  return (
    <section
      aria-labelledby="atlas-a11y-heading"
      class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-4 sm:p-5 space-y-3"
    >
      <header class="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:justify-between">
        <h2
          id="atlas-a11y-heading"
          class="font-mono text-[12px] uppercase tracking-[0.2em] text-[color:var(--color-signal-cyan)]"
        >
          ▸ Browse the corpus (accessible table)
        </h2>
        <p class="text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)]">
          {visibleRows.length.toLocaleString()} of {cards.length.toLocaleString()} cards
        </p>
      </header>
      <p class="text-[12px] text-[color:var(--color-text)] leading-relaxed">
        A keyboard- and screen-reader-friendly alternative to the canvas
        above. Same corpus, same destinations — clicking a row opens the
        same card detail page. Sort by any column; the canvas's color
        coding by agency is preserved here as the default sort.
      </p>

      {/* View toggle — sets the natural sort anchor; users can override
          via column-header clicks below. */}
      <div role="group" aria-label="Browse view" class="inline-flex font-mono text-[11px] uppercase tracking-[0.15em] border border-[color:var(--color-border)]">
        <button
          type="button"
          onClick={() => setViewAndSort("agency")}
          aria-pressed={view === "agency"}
          class={`px-3 py-1.5 transition-colors ${
            view === "agency"
              ? "bg-[color:var(--color-bg-elevated)] text-[color:var(--color-signal-cyan)]"
              : "text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
          }`}
        >
          By agency
        </button>
        <button
          type="button"
          onClick={() => setViewAndSort("date")}
          aria-pressed={view === "date"}
          class={`px-3 py-1.5 transition-colors border-l border-[color:var(--color-border)] ${
            view === "date"
              ? "bg-[color:var(--color-bg-elevated)] text-[color:var(--color-signal-cyan)]"
              : "text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)]"
          }`}
        >
          By date
        </button>
      </div>

      {/* Filter + redacted-only — labeled inputs so screen readers
          announce them as form fields, not stray text. */}
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <label class="flex-1 min-w-0">
          <span class="sr-only">Filter by title, agency, or location</span>
          <input
            type="search"
            value={filter}
            onInput={(e) => setFilter((e.target as HTMLInputElement).value)}
            placeholder="filter by title, agency, or location…"
            class="w-full"
          />
        </label>
        <label class="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] cursor-pointer">
          <input
            type="checkbox"
            checked={redactedOnly}
            onChange={(e) => setRedactedOnly((e.target as HTMLInputElement).checked)}
            class="accent-[color:var(--color-signal-red)]"
          />
          Redacted only
        </label>
      </div>

      <div class="overflow-x-auto border border-[color:var(--color-border)]">
        <table class="w-full text-[12px] font-mono border-collapse">
          <caption class="sr-only">
            PURSUE corpus cards, sortable by title, agency, type, incident
            date, or release date. Use the column header buttons to change
            sort. Each row is a link to the card detail page.
          </caption>
          <thead class="bg-[color:var(--color-bg-elevated)]">
            <tr>
              {COLUMNS.map((col) => {
                const isActive = sortKey === col.key;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    aria-sort={ariaSortValue(isActive, sortDir)}
                    class={`text-left px-2 py-2 text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] border-b border-[color:var(--color-border-bright)] ${col.thClass}`}
                  >
                    <button
                      type="button"
                      onClick={() => onHeaderClick(col.key)}
                      class={`inline-flex items-center gap-1 hover:text-[color:var(--color-text-bright)] focus-visible:text-[color:var(--color-signal-green)] ${
                        isActive ? "text-[color:var(--color-signal-cyan)]" : ""
                      }`}
                    >
                      {col.label}
                      <span aria-hidden="true">
                        {isActive ? (sortDir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  </th>
                );
              })}
              <th scope="col" class="text-left px-2 py-2 text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] border-b border-[color:var(--color-border-bright)]">
                <span class="sr-only">Open card</span>
                <span aria-hidden="true">→</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visibleRows.length === 0 ? (
              <tr>
                <td
                  colSpan={COLUMNS.length + 1}
                  class="px-2 py-3 text-center text-[color:var(--color-text-dim)]"
                >
                  No cards match the current filter.
                </td>
              </tr>
            ) : (
              visibleRows.map((c) => (
                <tr
                  key={c.card_id}
                  class="border-b border-[color:var(--color-border)] hover:bg-[color:var(--color-bg-elevated)]"
                >
                  {COLUMNS.map((col) => (
                    <td
                      key={col.key}
                      class="px-2 py-1.5 text-[color:var(--color-text)] align-top"
                    >
                      {col.render(c)}
                      {col.key === "title" && c.redacted && (
                        <span class="ml-2 text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-signal-red)]">
                          [redacted]
                        </span>
                      )}
                    </td>
                  ))}
                  <td class="px-2 py-1.5">
                    <a
                      href={`${base}/card/${c.card_id}/`}
                      class="text-[color:var(--color-signal-cyan)] underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)]"
                      aria-label={`Open card ${c.title}`}
                    >
                      open
                    </a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
