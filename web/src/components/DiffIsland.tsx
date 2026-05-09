import { useEffect, useMemo, useState } from "preact/hooks";
import type { CardMetadata, Manifest } from "../data/types";

interface Props {
  current: Manifest;
  base: string;
}

interface Snapshot {
  filename: string;
  manifest: Manifest;
}

interface DiffSet {
  added: CardMetadata[];
  removed: CardMetadata[];
}

function diff(current: CardMetadata[], previous: CardMetadata[]): DiffSet {
  const prevIds = new Set(previous.map((c) => c.card_id));
  const currIds = new Set(current.map((c) => c.card_id));
  return {
    added: current.filter((c) => !prevIds.has(c.card_id)),
    removed: previous.filter((c) => !currIds.has(c.card_id)),
  };
}

export default function DiffIsland({ current, base }: Props) {
  const [index, setIndex] = useState<string[] | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${base}/data/snapshots/index.json`)
      .then((r) => {
        // 404 is a legitimate "no snapshot yet" — show the empty state.
        // Any other non-OK status is a real error and must surface so we
        // don't silently mask 5xx as "no snapshots."
        if (r.status === 404) return [];
        if (!r.ok) {
          throw new Error(`snapshots index: HTTP ${r.status}`);
        }
        return r.json() as Promise<string[]>;
      })
      .then((data: string[]) => setIndex(data))
      .catch((e) => {
        setIndex([]);
        setError(String(e));
      });
  }, [base]);

  useEffect(() => {
    if (!index || index.length === 0) return;
    const filename = index[0];
    fetch(`${base}/data/snapshots/${filename}`)
      .then((r) => r.json() as Promise<Manifest>)
      .then((m) => setSnapshot({ filename, manifest: m }))
      .catch((e) => setError(String(e)));
  }, [index, base]);

  const result = useMemo(() => {
    if (!snapshot) return null;
    return diff(current.cards, snapshot.manifest.cards);
  }, [current, snapshot]);

  if (index === null) {
    return (
      <div class="space-y-3">
        <div class="pi-sweep h-8"></div>
        <p class="pi-loading text-xs">LOADING SNAPSHOTS<span class="pi-caret"></span></p>
      </div>
    );
  }

  // Error trumps the empty-state — a 5xx on the snapshots index was getting
  // rendered as "no prior snapshot" before, which silently hid real failures.
  if (error) {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-red)]">
        [ERR] Failed to load snapshot: {error}
      </p>
    );
  }

  if (index.length === 0) {
    return (
      <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-5 font-mono text-sm text-[color:var(--color-text)] pi-bracket relative scanlines-soft space-y-2">
        <p class="text-[color:var(--color-signal-amber)] uppercase tracking-[0.18em] text-xs">
          [NO PRIOR SNAPSHOT]
        </p>
        <p>
          Diff compares{" "}
          <code class="text-[color:var(--color-signal-cyan)]">latest.json</code>{" "}
          against any previous manifest under{" "}
          <code class="text-[color:var(--color-signal-cyan)]">/data/snapshots/</code>.
          Once Release 02 lands and the snapshot is committed, this surface
          will report what changed.
        </p>
        <p class="text-[11px] text-[color:var(--color-text-dim)] border-t border-[color:var(--color-border)] pt-2 mt-3">
          CURRENT · {new Date(current.fetched_at).toISOString().slice(0, 10)}
          <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
          {current.cards.length} CARDS
          <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
          CSV_SHA256 <code class="text-[color:var(--color-signal-cyan)]">{current.csv_sha256.slice(0, 12)}</code>
        </p>
      </div>
    );
  }

  if (!result || !snapshot) {
    return (
      <div class="space-y-3">
        <div class="pi-sweep h-8"></div>
        <p class="pi-loading text-xs">DECLASSIFYING<span class="pi-caret"></span></p>
      </div>
    );
  }

  return (
    <div class="space-y-6">
      <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] border-b border-[color:var(--color-border)] pb-2">
        VS
        <code class="ml-2 text-[color:var(--color-signal-cyan)]">{snapshot.filename}</code>
        <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
        {snapshot.manifest.cards.length} CARDS
      </div>
      <DiffSection title="ADDED" cards={result.added} tone="green" base={base} />
      <DiffSection title="REMOVED" cards={result.removed} tone="red" base={base} />
    </div>
  );
}

function DiffSection({
  title,
  cards,
  tone,
  base,
}: {
  title: string;
  cards: CardMetadata[];
  tone: "green" | "red";
  base: string;
}) {
  const colorVar = tone === "green" ? "--color-signal-green" : "--color-signal-red";
  const sym = tone === "green" ? "+" : "-";
  return (
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em]">
        <span class={`inline-block h-2 w-2 rounded-full bg-[color:var(${colorVar})] shadow-[0_0_8px_var(${colorVar})]`}></span>
        <span class={`text-[color:var(${colorVar})]`}>{title}</span>
        <span class="text-[color:var(--color-text-dim)]">({cards.length})</span>
      </h2>
      {cards.length === 0 ? (
        <p class="font-mono text-[11px] text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] pl-4">
          ── NONE ──
        </p>
      ) : (
        <ul class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 divide-y divide-[color:var(--color-border)] font-mono text-xs">
          {cards.map((c) => (
            <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
              <a href={`${base}/card/${c.card_id}`} class="flex items-baseline gap-3">
                <span class={`text-[color:var(${colorVar})]`}>{sym}</span>
                <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] w-10 shrink-0">
                  {c.asset_type}
                </span>
                <span class="text-[color:var(--color-text-bright)] line-clamp-1">{c.title}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
