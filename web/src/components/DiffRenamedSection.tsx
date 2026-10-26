import type { RenamedEntry } from "./diff-helpers.ts";
import { describeRenamedRow } from "./diff-renamed.ts";

/**
 * Cards whose card_id changed between two snapshots, collapsed through
 * `data/card-aliases.json`. Where the alias records the byte change behind
 * the rename (R7C.13), the row also shows its nature and the short byte
 * shas on each side; otherwise it shows the alias method alone, as before.
 */
export default function DiffRenamedSection({
  renamed,
  base,
}: {
  renamed: RenamedEntry[];
  base: string;
}) {
  return (
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em]">
        <span class="inline-block h-2 w-2 rounded-full bg-[color:var(--color-signal-cyan)] shadow-[0_0_8px_var(--color-signal-cyan)]"></span>
        <span class="text-[color:var(--color-signal-cyan)]">RENAMED</span>
        <span class="text-[color:var(--color-text-dim)]">({renamed.length})</span>
      </h2>
      {renamed.length === 0 ? (
        <p class="font-mono text-[11px] text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] pl-4">── NONE ──</p>
      ) : (
        <ul class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 divide-y divide-[color:var(--color-border)] font-mono text-xs">
          {renamed.map((r) => {
            const d = describeRenamedRow(r);
            return (
              <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
                <a href={`${base}/card/${r.to.card_id}`} class="flex items-baseline gap-3 flex-wrap">
                  <span class="text-[color:var(--color-signal-cyan)]">↻</span>
                  <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] w-10 shrink-0">{r.to.asset_type}</span>
                  <span class="text-[color:var(--color-text-bright)] line-clamp-1 flex-1">{r.to.title}</span>
                  {d.changeNature && (
                    <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-signal-cyan)]" title="nature of change">
                      {d.changeNature}
                    </span>
                  )}
                  {d.shaChange && (
                    <code class="text-[10px] text-[color:var(--color-text-dim)]" title={`byte sha256: ${d.shaChange.full}`}>
                      {d.shaChange.short}
                    </code>
                  )}
                  <span class="text-[10px] text-[color:var(--color-text-faint)]" title="alias method">{d.method}</span>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
