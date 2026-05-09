import { useEffect, useState } from "preact/hooks";
import type { CardNovelty, NoveltyMatch, NoveltyPayload } from "../data/types";
import { DISCLOSURE_TONE } from "./NoveltyFilter";

interface Props {
  cardId: string;
  base: string;
}

interface State {
  loaded: boolean;
  available: boolean;
  archiveId: string;
  card: CardNovelty | null;
}

const EMPTY: State = { loaded: false, available: false, archiveId: "", card: null };

// Pretty corpus name for the synthetic placeholder (and a fallback rule
// for whatever real corpora ship later).
function corpusLabel(archiveId: string): string {
  if (archiveId === "synthetic-placeholder") return "synthetic placeholder corpus";
  if (archiveId === "blackvault") return "Black Vault";
  return archiveId;
}

export default function CardProvenance({ cardId, base }: Props) {
  const [state, setState] = useState<State>(EMPTY);

  useEffect(() => {
    let cancelled = false;
    fetch(`${base}/data/novelty.json`, { cache: "force-cache" })
      .then((r) => (r.ok ? r.json() : null))
      .then((payload: NoveltyPayload | null) => {
        if (cancelled) return;
        if (!payload) {
          setState({ ...EMPTY, loaded: true });
          return;
        }
        setState({
          loaded: true,
          available: true,
          archiveId: payload.archive_id ?? "",
          card: payload.cards?.[cardId] ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ ...EMPTY, loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, [cardId, base]);

  if (!state.loaded) return null; // server-side / loading: render nothing

  if (!state.available) {
    return (
      <Section>
        <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
          (novelty comparison not yet computed for this corpus)
        </p>
      </Section>
    );
  }

  const card = state.card;
  if (!card) {
    return (
      <Section archiveId={state.archiveId}>
        <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
          No novelty record for this card — likely no embeddable text was
          extracted from it.
        </p>
      </Section>
    );
  }

  if (card.disclosure_status === "novel") {
    return (
      <Section archiveId={state.archiveId} status={card.disclosure_status}>
        <p class="text-sm text-[color:var(--color-text)]">
          No close matches found in the {corpusLabel(state.archiveId)}. The
          highest-similarity reference page scored{" "}
          <code class="text-[color:var(--color-signal-cyan)]">
            {(card.matches[0]?.similarity ?? 0).toFixed(3)}
          </code>{" "}
          (threshold for "previously disclosed" is 0.85).
        </p>
        <Caveat archiveId={state.archiveId} />
      </Section>
    );
  }

  return (
    <Section archiveId={state.archiveId} status={card.disclosure_status}>
      <p class="text-sm text-[color:var(--color-text)]">
        Closest matches in the {corpusLabel(state.archiveId)}:
      </p>
      <ul class="space-y-2 font-mono text-xs">
        {card.matches.slice(0, 3).map((m) => (
          <MatchRow match={m} />
        ))}
      </ul>
      <Caveat archiveId={state.archiveId} />
    </Section>
  );
}

function MatchRow({ match }: { match: NoveltyMatch }) {
  return (
    <li class="border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-2 flex gap-3 items-baseline">
      <span class="text-[color:var(--color-signal-cyan)] tabular-nums">
        {match.similarity.toFixed(3)}
      </span>
      <span class="text-[color:var(--color-text-faint)] uppercase tracking-[0.15em] text-[10px]">
        page {match.page}
      </span>
      <span class="text-[color:var(--color-text)] truncate">
        {match.ref_card_id ?? "—"}
      </span>
      <span class="ml-auto text-[color:var(--color-text-faint)] text-[10px] uppercase tracking-[0.15em]">
        {match.ref_archive}
      </span>
    </li>
  );
}

function Section({
  children,
  archiveId,
  status,
}: {
  children: any;
  archiveId?: string;
  status?: keyof typeof DISCLOSURE_TONE;
}) {
  const tone = status ? DISCLOSURE_TONE[status] : undefined;
  return (
    <section class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/60 p-5 space-y-3">
      <header class="flex flex-wrap items-center gap-2 border-b border-[color:var(--color-border)] pb-2">
        <h2 class="font-mono text-[12px] uppercase tracking-[0.2em] text-[color:var(--color-signal-green)]">
          ▸ Provenance
        </h2>
        {tone && (
          <span
            class={`text-[10px] font-mono uppercase tracking-[0.15em] px-1.5 py-0.5 border ${tone.bg} ${tone.fg} ${tone.border}`}
          >
            {tone.label}
          </span>
        )}
        {archiveId && (
          <span class="ml-auto text-[10px] font-mono text-[color:var(--color-text-faint)] uppercase tracking-[0.15em]">
            ref · {archiveId}
          </span>
        )}
      </header>
      {children}
    </section>
  );
}

function Caveat({ archiveId }: { archiveId: string }) {
  if (archiveId !== "synthetic-placeholder") return null;
  return (
    <p class="text-[11px] font-mono text-[color:var(--color-text-faint)] border-t border-[color:var(--color-border)] pt-2 leading-relaxed">
      Reference corpus: small synthetic placeholder. Full Black Vault
      integration (the canonical prior-disclosure FOIA archive) is in flight
      post-launch — see the{" "}
      <a
        href={`/methodology#novelty`}
        class="text-[color:var(--color-signal-cyan)] underline"
      >
        methodology page
      </a>{" "}
      for details.
    </p>
  );
}
