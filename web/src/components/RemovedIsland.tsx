import { useEffect, useState } from "preact/hooks";

interface RemovedCard {
  card_id: string;
  title: string;
  agency: string;
  asset_type: string;
  asset_filename?: string | null;
  asset_url?: string | null;
  release_date?: string | null;
  incident_date?: string | null;
  description?: string | null;
}

interface RemovalEvent {
  detected_at: string;
  prior_csv_sha256: string;
  new_csv_sha256: string;
  prior_fetched_at: string;
  card: RemovedCard;
}

interface RemovedPayload {
  removed: RemovalEvent[];
}

interface Props {
  base: string;
}

type Status = "loading" | "loaded" | "missing" | "error";

function shortSha(sha: string): string {
  return sha ? sha.slice(0, 12) : "?";
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso;
  }
}

export default function RemovedIsland({ base }: Props) {
  const [status, setStatus] = useState<Status>("loading");
  const [payload, setPayload] = useState<RemovedPayload | null>(null);

  useEffect(() => {
    fetch(`${base}/data/removed-cards.json`)
      .then((r) => {
        if (r.status === 404) {
          setStatus("missing");
          return null;
        }
        if (!r.ok) throw new Error(`fetch removed: ${r.status}`);
        return r.json() as Promise<RemovedPayload>;
      })
      .then((data) => {
        if (!data) return;
        setPayload(data);
        setStatus("loaded");
      })
      .catch((err) => {
        console.error(err);
        setStatus("error");
      });
  }, [base]);

  if (status === "loading") {
    return (
      <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
        LOADING REMOVAL LOG<span class="pi-caret"></span>
      </p>
    );
  }
  if (status === "missing") {
    return (
      <p class="font-mono text-xs text-[color:var(--color-text-dim)]">
        <span class="text-[color:var(--color-signal-green)]">[CLEAN]</span>
        <span class="ml-2">
          No removals on record. Every card seen in any prior scrape is
          still present in the upstream listing.
        </span>
      </p>
    );
  }
  if (status === "error") {
    return (
      <p class="font-mono text-sm text-[color:var(--color-signal-red)]">
        [ERR] Failed to load removal log.
      </p>
    );
  }

  const events = payload?.removed ?? [];

  return (
    <div class="space-y-4">
      <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-text-dim)] flex flex-wrap items-center gap-4 pb-2 border-b border-[color:var(--color-border)]">
        <span>
          <span class="text-[color:var(--color-signal-red)]">
            {events.length}
          </span>{" "}
          REMOVAL EVENT{events.length === 1 ? "" : "S"} ON RECORD
        </span>
      </div>

      <div class="space-y-3">
        {events.map((evt) => (
          <article
            key={`${evt.card.card_id}-${evt.detected_at}`}
            class="border border-[color:var(--color-signal-red)]/40 bg-[color:var(--color-bg)]/60 p-4 space-y-2"
          >
            <header class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <div class="font-mono text-[11px] uppercase tracking-[0.15em] text-[color:var(--color-signal-red)]">
                REMOVED {fmtDate(evt.detected_at)}
              </div>
              <div class="font-mono text-[10px] text-[color:var(--color-text-faint)]">
                {evt.card.agency} &middot; {evt.card.asset_type}
              </div>
            </header>
            <h2 class="font-mono text-sm font-semibold text-[color:var(--color-text-bright)] break-words">
              {evt.card.title}
            </h2>
            {evt.card.description && (
              <p class="text-xs text-[color:var(--color-text)] leading-relaxed line-clamp-3">
                {evt.card.description}
              </p>
            )}
            <dl class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px] font-mono pt-1 border-t border-[color:var(--color-border)]">
              <div>
                <dt class="text-[color:var(--color-text-faint)] uppercase tracking-[0.18em]">
                  Card_id
                </dt>
                <dd class="text-[color:var(--color-text-bright)] break-all">
                  {evt.card.card_id}
                </dd>
              </div>
              <div>
                <dt class="text-[color:var(--color-text-faint)] uppercase tracking-[0.18em]">
                  Release
                </dt>
                <dd class="text-[color:var(--color-text-bright)]">
                  {evt.card.release_date ?? "—"}
                </dd>
              </div>
              <div>
                <dt class="text-[color:var(--color-text-faint)] uppercase tracking-[0.18em]">
                  Incident
                </dt>
                <dd class="text-[color:var(--color-text-bright)]">
                  {evt.card.incident_date ?? "—"}
                </dd>
              </div>
              <div>
                <dt class="text-[color:var(--color-text-faint)] uppercase tracking-[0.18em]">
                  Csv-sha
                </dt>
                <dd class="text-[color:var(--color-text-bright)]" title={evt.new_csv_sha256}>
                  {shortSha(evt.prior_csv_sha256)} &rarr;{" "}
                  {shortSha(evt.new_csv_sha256)}
                </dd>
              </div>
            </dl>
            <nav class="flex flex-wrap gap-3 font-mono text-[11px] uppercase tracking-[0.15em] pt-1">
              <a
                href={`/card/${evt.card.card_id}/`}
                class="text-[color:var(--color-signal-cyan)] underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)]"
              >
                view preserved record &rarr;
              </a>
              <a
                href={`/pdf/${evt.card.card_id}.pdf`}
                class="text-[color:var(--color-signal-cyan)] underline decoration-[color:var(--color-border-bright)] hover:decoration-[color:var(--color-signal-cyan)]"
                target="_blank"
                rel="noreferrer"
              >
                download PDF (R2 mirror) &rarr;
              </a>
            </nav>
          </article>
        ))}
      </div>
    </div>
  );
}
