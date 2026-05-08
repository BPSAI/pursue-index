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
      .then((r) => (r.ok ? r.json() : []))
      .then((data: string[]) => setIndex(data))
      .catch(() => setIndex([]));
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
    return <p class="text-sm text-neutral-500">Loading snapshots…</p>;
  }

  if (index.length === 0) {
    return (
      <div class="rounded-md border border-neutral-800 bg-neutral-925 p-4 text-sm text-neutral-400">
        <p class="font-medium text-neutral-200 mb-1">No prior snapshot yet</p>
        <p>
          Diff view compares <code class="text-neutral-300">latest.json</code>
          against any previous manifest under
          <code class="mx-1 text-neutral-300">/data/snapshots/</code>. Once a
          second tranche lands and the snapshot is committed, this page will
          surface what changed.
        </p>
        <p class="mt-2 text-xs text-neutral-500">
          Current manifest fetched {new Date(current.fetched_at).toISOString().slice(0, 10)} ·
          {" "}{current.cards.length} cards · csv_sha256{" "}
          <code>{current.csv_sha256.slice(0, 12)}…</code>
        </p>
      </div>
    );
  }

  if (error) {
    return <p class="text-sm text-red-400">Failed to load snapshot: {error}</p>;
  }

  if (!result || !snapshot) {
    return <p class="text-sm text-neutral-500">Loading snapshot…</p>;
  }

  return (
    <div class="space-y-6">
      <div class="text-sm text-neutral-400">
        Comparing against <code class="text-neutral-200">{snapshot.filename}</code>
        {" "}({snapshot.manifest.cards.length} cards)
      </div>
      <DiffSection title="Added" cards={result.added} tone="emerald" base={base} />
      <DiffSection title="Removed" cards={result.removed} tone="red" base={base} />
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
  tone: "emerald" | "red";
  base: string;
}) {
  const dot = tone === "emerald" ? "bg-emerald-500" : "bg-red-500";
  return (
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 text-sm uppercase tracking-wider text-neutral-300">
        <span class={`inline-block h-2 w-2 rounded-full ${dot}`} />
        {title} ({cards.length})
      </h2>
      {cards.length === 0 ? (
        <p class="text-xs text-neutral-500">none</p>
      ) : (
        <ul class="text-sm divide-y divide-neutral-800 border border-neutral-800 rounded-md">
          {cards.map((c) => (
            <li class="px-3 py-2 hover:bg-neutral-925">
              <a href={`${base}/card/${c.card_id}`} class="flex items-baseline gap-2">
                <span class="text-[10px] uppercase tracking-wider text-neutral-500">
                  {c.asset_type}
                </span>
                <span class="text-neutral-200 line-clamp-1">{c.title}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
