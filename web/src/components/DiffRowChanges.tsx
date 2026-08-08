import { describeUnpairedRow, type UnpairedRow } from "./row-pairing.ts";

/**
 * Rows a card_id gained or lost between two snapshots.
 *
 * A card_id can be backed by several manifest rows (a document row plus
 * one or more video rows). Only rows that pair across the two snapshots
 * produce a field-level diff, so a card that gains a fourth video — or
 * loses one — has no field change to show. This section is where that
 * change is reported.
 */
export default function DiffRowChanges({
  rows,
  base,
}: {
  rows: UnpairedRow[];
  base: string;
}) {
  return (
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em]">
        <span class="inline-block h-2 w-2 rounded-full bg-[color:var(--color-signal-cyan)] shadow-[0_0_8px_var(--color-signal-cyan)]"></span>
        <span class="text-[color:var(--color-signal-cyan)]">ROW-LEVEL CHANGES</span>
        <span class="text-[color:var(--color-text-dim)]">({rows.length})</span>
      </h2>
      {rows.length === 0 ? (
        <p class="font-mono text-[11px] text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] pl-4">── NONE ──</p>
      ) : (
        <>
          <p class="font-mono text-[11px] text-[color:var(--color-text-dim)] pl-4">
            A card here kept its identity but gained or lost one of the manifest rows behind it —
            typically a video attached to, or withdrawn from, an existing document.
          </p>
          <ul class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 divide-y divide-[color:var(--color-border)] font-mono text-xs max-h-96 overflow-y-auto">
            {rows.map((entry) => {
              const d = describeUnpairedRow(entry);
              const color =
                d.verb === "ADDED" ? "--color-signal-green" : "--color-signal-red";
              return (
                <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
                  <a href={`${base}/card/${d.cardId}`} class="flex items-baseline gap-3 flex-wrap">
                    <span class={`text-[color:var(${color})]`}>{d.symbol}</span>
                    <span class={`text-[10px] uppercase tracking-[0.15em] text-[color:var(${color})] w-20 shrink-0`}>
                      {d.verb}
                    </span>
                    <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] w-10 shrink-0">
                      {d.assetType}
                    </span>
                    <code class="text-[color:var(--color-signal-cyan)] text-[10px]">{d.cardId.slice(0, 12)}</code>
                    <span class="text-[color:var(--color-text-bright)] line-clamp-1 flex-1">{d.title}</span>
                    <span class="text-[10px] text-[color:var(--color-text-faint)]">{d.detail}</span>
                  </a>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
