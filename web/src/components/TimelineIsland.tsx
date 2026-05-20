import { useMemo, useState } from "preact/hooks";
import type { CardMetadata } from "../data/types";
import { buildTimelineCards, summary, yearSpan, type DateEntry, type TimelineCard } from "./timeline-helpers.ts";

interface Props {
  cards: CardMetadata[];
  approved: DateEntry[];
  proposals: DateEntry[];
  base: string;
}

const AGENCY_COLOR: Record<string, string> = {
  "Department of War": "var(--color-signal-amber)",
  FBI: "var(--color-signal-green)",
  NASA: "var(--color-signal-cyan)",
  "Department of State": "var(--color-signal-violet)",
};

function agencyColor(agency: string): string {
  return AGENCY_COLOR[agency] ?? "var(--color-text-dim)";
}

const ALL_AGENCIES = ["Department of War", "FBI", "NASA", "Department of State"];
const ALL_TYPES = ["PDF", "VID", "IMG", "AUD"];

export default function TimelineIsland({ cards, approved, proposals, base }: Props) {
  const approvedByCard = useMemo(
    () => Object.fromEntries(approved.map((e) => [e.card_id, e])),
    [approved],
  );
  const proposalsByCard = useMemo(
    () => Object.fromEntries(proposals.map((e) => [e.card_id, e])),
    [proposals],
  );

  const items = useMemo(
    () => buildTimelineCards(cards, approvedByCard, proposalsByCard),
    [cards, approvedByCard, proposalsByCard],
  );

  const [showProposals, setShowProposals] = useState(true);
  const [agencyFilter, setAgencyFilter] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<string>("");

  const filtered = useMemo(() => {
    return items.filter((it) => {
      if (!showProposals && it.source === "proposal") return false;
      if (agencyFilter && it.card.agency !== agencyFilter) return false;
      if (typeFilter && it.card.asset_type !== typeFilter) return false;
      return true;
    });
  }, [items, showProposals, agencyFilter, typeFilter]);

  const stats = useMemo(() => summary(items), [items]);
  const span = useMemo(() => yearSpan(filtered), [filtered]);

  const dated = filtered.filter((it) => it.yearPos !== null);
  const abstained = filtered.filter((it) => it.precision === "none" && it.abstention);
  const undated = filtered.filter((it) => it.precision === "none" && !it.abstention);

  return (
    <div class="space-y-6">
      {/* Status readout */}
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-4 font-mono text-xs space-y-1.5">
        <div class="flex flex-wrap gap-x-6 gap-y-1 text-[color:var(--color-text)]">
          <span>
            <span class="text-[color:var(--color-text-faint)]">total:</span>{" "}
            <span class="text-[color:var(--color-text-bright)]">{stats.total}</span>
          </span>
          <span>
            <span class="text-[color:var(--color-text-faint)]">approved:</span>{" "}
            <span class="text-[color:var(--color-signal-green)]">{stats.approved}</span>
          </span>
          <span>
            <span class="text-[color:var(--color-text-faint)]">tentative (proposals):</span>{" "}
            <span class="text-[color:var(--color-signal-cyan)]">{stats.proposal}</span>
          </span>
          <span>
            <span class="text-[color:var(--color-text-faint)]">abstained:</span>{" "}
            <span class="text-[color:var(--color-signal-amber)]">{stats.abstained}</span>
          </span>
          {stats.undated > 0 && (
            <span>
              <span class="text-[color:var(--color-text-faint)]">undated:</span>{" "}
              <span class="text-[color:var(--color-text-dim)]">{stats.undated}</span>
            </span>
          )}
        </div>
        <div class="text-[10px] text-[color:var(--color-text-faint)]">
          Approved entries come from <code class="text-[color:var(--color-signal-cyan)]">data/display_dates.json</code> (operator-curated, point or range). Tentative entries are the writer-agent's draft proposals shown as faint ghosts; they become solid once the operator approves them in the curate UI.
        </div>
      </div>

      {/* Filters */}
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-3 flex flex-wrap gap-3 items-end">
        <div class="flex flex-col gap-1">
          <label class="font-mono text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]" htmlFor="tl-agency">
            Agency
          </label>
          <select
            id="tl-agency"
            value={agencyFilter}
            onChange={(e) => setAgencyFilter((e.target as HTMLSelectElement).value)}
            class="bg-[color:var(--color-bg-deep)] text-[color:var(--color-text-bright)] border border-[color:var(--color-border)] px-2 py-1 font-mono text-xs"
          >
            <option value="">all</option>
            {ALL_AGENCIES.map((a) => (
              <option value={a}>{a}</option>
            ))}
          </select>
        </div>
        <div class="flex flex-col gap-1">
          <label class="font-mono text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]" htmlFor="tl-type">
            Type
          </label>
          <select
            id="tl-type"
            value={typeFilter}
            onChange={(e) => setTypeFilter((e.target as HTMLSelectElement).value)}
            class="bg-[color:var(--color-bg-deep)] text-[color:var(--color-text-bright)] border border-[color:var(--color-border)] px-2 py-1 font-mono text-xs"
          >
            <option value="">all</option>
            {ALL_TYPES.map((t) => (
              <option value={t}>{t}</option>
            ))}
          </select>
        </div>
        <label class="flex items-center gap-2 font-mono text-[11px] text-[color:var(--color-text)]">
          <input
            type="checkbox"
            checked={showProposals}
            onChange={(e) => setShowProposals((e.target as HTMLInputElement).checked)}
          />
          show tentative proposals
        </label>
      </div>

      {/* Timeline strip */}
      {span ? (
        <TimelineStrip items={dated} span={span} base={base} />
      ) : (
        <p class="font-mono text-xs text-[color:var(--color-text-dim)] italic">No dated entries to plot in the current filter.</p>
      )}

      {/* Abstention bucket */}
      {abstained.length > 0 && (
        <section class="space-y-2">
          <h2 class="font-mono text-[11px] uppercase tracking-[0.18em] flex items-center gap-2">
            <span class="inline-block h-2 w-2 rounded-full bg-[color:var(--color-signal-amber)] shadow-[0_0_8px_var(--color-signal-amber)]"></span>
            <span class="text-[color:var(--color-signal-amber)]">UNDATED — abstained</span>
            <span class="text-[color:var(--color-text-dim)]">({abstained.length})</span>
          </h2>
          <p class="font-mono text-[10px] text-[color:var(--color-text-faint)]">
            Decade-spanning files (FBI omnibus sections, Box-N incident summaries, multi-year compilations) have no single defensible date. They're shown here with their coverage-range reason.
          </p>
          <ul class="grid grid-cols-1 md:grid-cols-2 gap-2 font-mono text-xs">
            {abstained.map((it) => (
              <li class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-3 hover:border-[color:var(--color-signal-amber)] transition-colors">
                <a href={`${base}/card/${it.card.card_id}`} class="block">
                  <div class="flex items-baseline gap-2">
                    <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)]">{it.card.asset_type}</span>
                    <span class="text-[color:var(--color-text-bright)] line-clamp-1 flex-1">{it.card.title}</span>
                  </div>
                  <p class="mt-1 text-[10px] text-[color:var(--color-text-dim)] line-clamp-3 italic">
                    {it.abstention}
                  </p>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function TimelineStrip({
  items,
  span,
  base,
}: {
  items: TimelineCard[];
  span: [number, number];
  base: string;
}) {
  const [minYear, maxYear] = span;
  const totalYears = Math.max(1, maxYear - minYear);
  const decades = useMemo(() => {
    const out: number[] = [];
    const first = Math.floor(minYear / 10) * 10;
    const last = Math.ceil(maxYear / 10) * 10;
    for (let y = first; y <= last; y += 10) out.push(y);
    return out;
  }, [minYear, maxYear]);

  // Project a yearPos to a 0-100% horizontal position.
  function pct(yearPos: number): string {
    const p = ((yearPos - minYear) / totalYears) * 100;
    return `${Math.min(100, Math.max(0, p))}%`;
  }

  return (
    <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-4">
      <div class="relative" style="height: 240px;">
        {/* Decade ticks + labels along the bottom */}
        <div class="absolute inset-x-0 bottom-0 h-8 border-t border-[color:var(--color-border)]">
          {decades.map((d) => (
            <div
              class="absolute top-0 bottom-0 flex flex-col items-center"
              style={`left: ${pct(d)};`}
            >
              <div class="w-px h-2 bg-[color:var(--color-border-bright)]"></div>
              <span class="font-mono text-[10px] text-[color:var(--color-text-faint)] mt-1">{d}</span>
            </div>
          ))}
        </div>

        {/* Card dots */}
        <div class="absolute inset-x-0 top-0 bottom-8">
          {items.map((it, i) => {
            if (it.yearPos == null) return null;
            // Stagger Y position based on a stable hash of card_id so overlapping
            // dots don't perfectly stack (a tiny ergonomic improvement; not full
            // beeswarm).
            const hash = it.card.card_id.charCodeAt(0) + it.card.card_id.charCodeAt(1) + i;
            const yPct = 10 + (hash % 80); // 10-90%
            const color = agencyColor(it.card.agency);
            const solid = it.source === "approved";
            const ringClass = solid ? "ring-1 ring-offset-0" : "";
            return (
              <a
                href={`${base}/card/${it.card.card_id}`}
                title={`${it.card.title} — ${it.display_date} (${it.card.agency}) [${it.source}]`}
                class="absolute hover:scale-150 focus:scale-150 transition-transform duration-150 outline-none"
                style={`left: ${pct(it.yearPos)}; top: ${yPct}%; transform: translate(-50%, -50%);`}
              >
                <span
                  aria-label={`${it.card.title}, ${it.display_date}`}
                  class={`block h-2 w-2 rounded-full ${ringClass}`}
                  style={`background: ${solid ? color : "transparent"}; border: 1px solid ${color}; opacity: ${solid ? 1 : 0.55};`}
                />
              </a>
            );
          })}
        </div>
      </div>
      <p class="font-mono text-[10px] text-[color:var(--color-text-faint)] mt-4">
        Each dot is one card plotted at its display_date. Solid = operator-approved; hollow = agent proposal. Color = agency (
        <span style={`color: var(--color-signal-amber);`}>DoW</span>,{" "}
        <span style={`color: var(--color-signal-green);`}>FBI</span>,{" "}
        <span style={`color: var(--color-signal-cyan);`}>NASA</span>,{" "}
        <span style={`color: var(--color-signal-violet);`}>State</span>). Hover for title; click to open the card.
      </p>
    </div>
  );
}
