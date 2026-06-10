import { useEffect, useMemo, useState } from "preact/hooks";
import type { AliasEntry, CardMetadata, Manifest } from "../data/types";
import {
  buildDiffParams,
  diffWithAliases,
  fieldOnlyChanges,
  normalizeSnapshotIndex,
  parseDiffParams,
  resolveAliases,
  selectDefaultPair,
  type SnapshotIndexMeta,
} from "./diff-helpers.ts";
import DiffTimeline from "./DiffTimeline.tsx";

interface Props {
  current: Manifest;
  base: string;
  aliases: AliasEntry[];
}

interface Snapshot {
  filename: string;
  manifest: Manifest;
}

interface SnapshotMeta {
  filename: string;
  fetched_at?: string;
  card_count?: number;
  csv_sha?: string;
}

function shaPrefix(filename: string): string {
  return filename.replace(/\.json$/i, "").slice(0, 8);
}

function dateLabel(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

function snapshotLabel(meta: SnapshotMeta): string {
  const date = meta.fetched_at ? dateLabel(meta.fetched_at) : "—";
  const count = meta.card_count != null ? `${meta.card_count} cards` : "?? cards";
  return `${shaPrefix(meta.filename)} · ${date} · ${count}`;
}

export default function DiffIsland({ current, base, aliases }: Props) {
  const aliasMap = useMemo(() => resolveAliases(aliases ?? []), [aliases]);

  // index = chronologically-sorted snapshot filenames from index.json.
  const [index, setIndex] = useState<string[] | null>(null);
  // indexMeta = filename → label metadata (date, card count) carried by
  // the enriched index.json, so selectors label every snapshot without
  // first lazily fetching its full manifest (no more "?? cards").
  const [indexMeta, setIndexMeta] = useState<Record<string, SnapshotIndexMeta>>({});
  // snapshots = filename → loaded Manifest. Lazy: only populated as needed.
  const [snapshots, setSnapshots] = useState<Record<string, Manifest>>({});
  // selectedFrom / selectedTo = filenames. `to` may be a real snapshot OR the
  // synthetic "@current" sentinel meaning "compare against latest.json".
  const [selectedFrom, setSelectedFrom] = useState<string | null>(null);
  const [selectedTo, setSelectedTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Synthetic sentinel for `current` (latest.json) so the right-side
  // selector can point at "latest" without it being an entry in
  // /data/snapshots/index.json. We materialize it lazily in
  // `manifestFor()` below.
  const CURRENT_SENTINEL = "@current";

  function manifestFor(filename: string | null): Manifest | null {
    if (!filename) return null;
    if (filename === CURRENT_SENTINEL) return current;
    return snapshots[filename] ?? null;
  }

  // ---- Load the snapshot index once ----
  useEffect(() => {
    fetch(`${base}/data/snapshots/index.json`)
      .then((r) => {
        if (r.status === 404) return [];
        if (!r.ok) throw new Error(`snapshots index: HTTP ${r.status}`);
        return r.json() as Promise<unknown>;
      })
      .then((data: unknown) => {
        // Tolerant of both the legacy bare-filename list and the
        // enriched {filename, fetched_at, card_count} objects.
        const { filenames, meta } = normalizeSnapshotIndex(data);
        setIndex(filenames);
        setIndexMeta(meta);
      })
      .catch((e) => {
        setIndex([]);
        setError(String(e));
      });
  }, [base]);

  // ---- Pick initial pair from URL or fall back to the default ----
  useEffect(() => {
    if (!index) return;
    const fromUrl = typeof window !== "undefined" ? parseDiffParams(window.location.search) : { from: null, to: null };
    const fromIsValid = fromUrl.from && (fromUrl.from === CURRENT_SENTINEL || index.includes(fromUrl.from));
    const toIsValid = fromUrl.to && (fromUrl.to === CURRENT_SENTINEL || index.includes(fromUrl.to));
    if (fromIsValid && toIsValid) {
      setSelectedFrom(fromUrl.from!);
      setSelectedTo(fromUrl.to!);
      return;
    }
    // Default: compare immediate-prior snapshot vs current (latest.json).
    // We use the synthetic sentinel on the right so the page renders
    // even when latest.json doesn't have its own entry in the index.
    const { from } = selectDefaultPair([...index, CURRENT_SENTINEL]);
    setSelectedFrom(from ?? null);
    setSelectedTo(CURRENT_SENTINEL);
  }, [index]);

  // ---- Sync URL when selection changes ----
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (selectedFrom == null && selectedTo == null) return;
    const qs = buildDiffParams(selectedFrom, selectedTo);
    const next = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    if (window.location.pathname + (window.location.search || "") !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [selectedFrom, selectedTo]);

  // ---- Lazy-fetch any selected snapshot we don't have yet ----
  useEffect(() => {
    const pending = [selectedFrom, selectedTo].filter(
      (f): f is string => !!f && f !== CURRENT_SENTINEL && !snapshots[f],
    );
    if (pending.length === 0) return;
    for (const f of pending) {
      fetch(`${base}/data/snapshots/${f}`)
        .then((r) => {
          if (!r.ok) throw new Error(`snapshot ${f}: HTTP ${r.status}`);
          return r.json() as Promise<Manifest>;
        })
        .then((m) => setSnapshots((prev) => ({ ...prev, [f]: m })))
        .catch((e) => setError(String(e)));
    }
  }, [selectedFrom, selectedTo, base, snapshots]);

  const fromMeta: SnapshotMeta | null = selectedFrom
    ? {
        filename: selectedFrom,
        fetched_at: manifestFor(selectedFrom)?.fetched_at,
        card_count: manifestFor(selectedFrom)?.cards.length,
      }
    : null;
  const toMeta: SnapshotMeta | null = selectedTo
    ? {
        filename: selectedTo,
        fetched_at: manifestFor(selectedTo)?.fetched_at,
        card_count: manifestFor(selectedTo)?.cards.length,
      }
    : null;

  const diffResult = useMemo(() => {
    const fromM = manifestFor(selectedFrom);
    const toM = manifestFor(selectedTo);
    if (!fromM || !toM) return null;
    return diffWithAliases(fromM.cards, toM.cards, aliasMap);
  }, [selectedFrom, selectedTo, snapshots, aliasMap]);

  const fieldChanges = useMemo(() => {
    const fromM = manifestFor(selectedFrom);
    const toM = manifestFor(selectedTo);
    if (!fromM || !toM) return null;
    return fieldOnlyChanges(fromM.cards, toM.cards);
  }, [selectedFrom, selectedTo, snapshots]);

  // ---- Render branches -------------------------------------------------

  if (index === null) {
    return (
      <div class="space-y-3">
        <div class="pi-sweep h-8"></div>
        <p class="pi-loading text-xs">LOADING SNAPSHOTS<span class="pi-caret"></span></p>
      </div>
    );
  }

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
        <p class="text-[color:var(--color-signal-amber)] uppercase tracking-[0.18em] text-xs">[NO PRIOR SNAPSHOT]</p>
        <p>
          The diff page compares two snapshots under{" "}
          <code class="text-[color:var(--color-signal-cyan)]">/data/snapshots/</code>. Once a snapshot has been
          committed, this surface will report what changed.
        </p>
      </div>
    );
  }

  const options: SnapshotMeta[] = [
    ...index.map((f) => ({
      filename: f,
      // Prefer the index's label metadata; fall back to a manifest
      // already loaded by a prior selection. Either path avoids the
      // "?? cards" placeholder for snapshots that haven't been fetched.
      fetched_at: indexMeta[f]?.fetched_at ?? snapshots[f]?.fetched_at,
      card_count: indexMeta[f]?.card_count ?? snapshots[f]?.cards.length,
    })),
    { filename: CURRENT_SENTINEL, fetched_at: current.fetched_at, card_count: current.cards.length },
  ];

  function onChange(side: "from" | "to") {
    return (e: Event) => {
      const v = (e.target as HTMLSelectElement).value || null;
      if (side === "from") setSelectedFrom(v);
      else setSelectedTo(v);
    };
  }

  function swap() {
    setSelectedFrom(selectedTo);
    setSelectedTo(selectedFrom);
  }

  const bothLoaded = diffResult != null && fieldChanges != null;

  function onJump(right: string) {
    // Click on a tick → set selectedTo = right, selectedFrom = prior in chronological order.
    // The CURRENT_SENTINEL sits at the end of the chronological list.
    const ordered = [...index, CURRENT_SENTINEL];
    const idx = ordered.indexOf(right);
    if (idx < 0) return;
    const prior = idx > 0 ? ordered[idx - 1] : null;
    setSelectedFrom(prior);
    setSelectedTo(right);
  }

  return (
    <div class="space-y-6">
      <DiffTimeline
        index={index}
        loaded={snapshots}
        currentFilename={CURRENT_SENTINEL}
        currentManifest={current}
        selectedFrom={selectedFrom}
        selectedTo={selectedTo}
        onJump={onJump}
      />
      <div class="flex flex-wrap items-end gap-3 border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-4">
        <div class="flex flex-col gap-1">
          <label class="font-mono text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]" htmlFor="diff-from">
            From (older)
          </label>
          <select
            id="diff-from"
            value={selectedFrom ?? ""}
            onChange={onChange("from")}
            class="bg-[color:var(--color-bg-deep)] text-[color:var(--color-text-bright)] border border-[color:var(--color-border)] px-2 py-1.5 font-mono text-xs min-w-[18rem]"
          >
            <option value="">— select snapshot —</option>
            {options.map((o) => (
              <option value={o.filename} disabled={o.filename === selectedTo}>
                {o.filename === CURRENT_SENTINEL ? `CURRENT · ${snapshotLabel(o).slice(snapshotLabel(o).indexOf("·") + 2)}` : snapshotLabel(o)}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={swap}
          title="Swap from / to"
          class="font-mono text-xs px-2 py-1.5 border border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-cyan)] hover:border-[color:var(--color-signal-cyan)]"
        >
          ⇄
        </button>
        <div class="flex flex-col gap-1">
          <label class="font-mono text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]" htmlFor="diff-to">
            To (newer)
          </label>
          <select
            id="diff-to"
            value={selectedTo ?? ""}
            onChange={onChange("to")}
            class="bg-[color:var(--color-bg-deep)] text-[color:var(--color-text-bright)] border border-[color:var(--color-border)] px-2 py-1.5 font-mono text-xs min-w-[18rem]"
          >
            <option value="">— select snapshot —</option>
            {options.map((o) => (
              <option value={o.filename} disabled={o.filename === selectedFrom}>
                {o.filename === CURRENT_SENTINEL ? `CURRENT · ${snapshotLabel(o).slice(snapshotLabel(o).indexOf("·") + 2)}` : snapshotLabel(o)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!bothLoaded ? (
        <div class="space-y-3">
          <div class="pi-sweep h-8"></div>
          <p class="pi-loading text-xs">DECLASSIFYING<span class="pi-caret"></span></p>
        </div>
      ) : (
        <DiffBody
          diff={diffResult!}
          fieldChanges={fieldChanges!}
          fromMeta={fromMeta}
          toMeta={toMeta}
          base={base}
        />
      )}
    </div>
  );
}

function DiffBody({
  diff,
  fieldChanges,
  fromMeta,
  toMeta,
  base,
}: {
  diff: ReturnType<typeof diffWithAliases>;
  fieldChanges: ReturnType<typeof fieldOnlyChanges>;
  fromMeta: SnapshotMeta | null;
  toMeta: SnapshotMeta | null;
  base: string;
}) {
  return (
    <div class="space-y-6">
      <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] border-b border-[color:var(--color-border)] pb-2">
        {fromMeta && <span>FROM <code class="text-[color:var(--color-signal-cyan)]">{shaPrefix(fromMeta.filename)}</code> ({dateLabel(fromMeta.fetched_at)} · {fromMeta.card_count} cards)</span>}
        <span class="mx-2 text-[color:var(--color-text-faint)]">→</span>
        {toMeta && <span>TO <code class="text-[color:var(--color-signal-cyan)]">{shaPrefix(toMeta.filename)}</code> ({dateLabel(toMeta.fetched_at)} · {toMeta.card_count} cards)</span>}
      </div>
      <DiffSection title="ADDED" cards={diff.added} tone="green" base={base} />
      <DiffSection title="REMOVED" cards={diff.removed} tone="red" base={base} />
      <RenamedSection renamed={diff.renamed} base={base} />
      <FieldChangedSection fieldChanges={fieldChanges} base={base} />
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
        <p class="font-mono text-[11px] text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] pl-4">── NONE ──</p>
      ) : (
        <ul class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 divide-y divide-[color:var(--color-border)] font-mono text-xs">
          {cards.map((c) => (
            <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
              <a href={`${base}/card/${c.card_id}`} class="flex items-baseline gap-3">
                <span class={`text-[color:var(${colorVar})]`}>{sym}</span>
                <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] w-10 shrink-0">{c.asset_type}</span>
                <span class="text-[color:var(--color-text-bright)] line-clamp-1">{c.title}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RenamedSection({
  renamed,
  base,
}: {
  renamed: ReturnType<typeof diffWithAliases>["renamed"];
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
          {renamed.map((r) => (
            <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
              <a href={`${base}/card/${r.to.card_id}`} class="flex items-baseline gap-3 flex-wrap">
                <span class="text-[color:var(--color-signal-cyan)]">↻</span>
                <span class="text-[10px] uppercase tracking-[0.15em] text-[color:var(--color-text-faint)] w-10 shrink-0">{r.to.asset_type}</span>
                <span class="text-[color:var(--color-text-bright)] line-clamp-1 flex-1">{r.to.title}</span>
                <span class="text-[10px] text-[color:var(--color-text-faint)]" title="alias method">{r.method}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FieldChangedSection({
  fieldChanges,
  base,
}: {
  fieldChanges: ReturnType<typeof fieldOnlyChanges>;
  base: string;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em]">
        <span class="inline-block h-2 w-2 rounded-full bg-[color:var(--color-signal-amber)] shadow-[0_0_8px_var(--color-signal-amber)]"></span>
        <span class="text-[color:var(--color-signal-amber)]">FIELD-ONLY CHANGES</span>
        <span class="text-[color:var(--color-text-dim)]">({fieldChanges.length})</span>
        {fieldChanges.length > 0 && (
          <button
            type="button"
            class="ml-auto text-[10px] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-cyan)] uppercase tracking-[0.15em]"
            onClick={() => setExpanded(!expanded)}
          >
            [{expanded ? "collapse" : "expand"}]
          </button>
        )}
      </h2>
      {fieldChanges.length === 0 ? (
        <p class="font-mono text-[11px] text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] pl-4">── NONE ──</p>
      ) : !expanded ? (
        <p class="font-mono text-[11px] text-[color:var(--color-text-dim)] pl-4">
          {fieldChanges.length} card(s) had metadata (title, agency, alt-text, classification, etc.) change without being added or removed. Expand to see which fields changed per card.
        </p>
      ) : (
        <ul class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 divide-y divide-[color:var(--color-border)] font-mono text-xs max-h-96 overflow-y-auto">
          {fieldChanges.map((fc) => (
            <li class="px-3 py-1.5 hover:bg-[color:var(--color-bg-elevated)]">
              <a href={`${base}/card/${fc.card_id}`} class="flex items-baseline gap-3 flex-wrap">
                <span class="text-[color:var(--color-signal-amber)]">~</span>
                <code class="text-[color:var(--color-signal-cyan)] text-[10px]">{fc.card_id.slice(0, 12)}</code>
                <span class="text-[color:var(--color-text-faint)] text-[10px]">→</span>
                <span class="text-[color:var(--color-text)] text-[10px]">{fc.fields.join(", ")}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
