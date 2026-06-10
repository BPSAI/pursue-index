// ChatIsland — the headline UI surface.
//
// Single-turn v1: each user submission produces one assistant message
// with streaming text + a citation list. No history persistence.
//
// Behavior:
//   - Empty state shows suggested queries (clickable → populate input).
//   - Provider is `AnthropicServerProvider` by default; if the user has
//     saved an Anthropic key in localStorage, switch to BYOK.
//   - Streaming: each text delta appends to the active assistant message
//     and ticks a signal-green caret while in flight.
//   - Errors: rate-limit / budget-exceeded show a CTA to open Settings
//     (and offer BYOK). Other errors render in red.
//   - Cmd/Ctrl+Enter submits; plain Enter inserts a newline.
//   - Citations: rendered both inline (numbered chips) and as a list
//     under the assistant message.

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  AnthropicBYOKProvider,
  AnthropicServerProvider,
  type Chunk,
  type Citation,
  type LLMProvider,
} from "../lib/llm-provider";
import { loadBYOKConfig, type BYOKConfig } from "../lib/byok";
import ChatSettingsPanel from "./ChatSettingsPanel";
import { segmentWithCitations } from "../lib/citation-render";
import {
  EMPTY_FILTERS,
  cardMatchesFilters,
  parseFiltersFromQuery,
  type SearchFilters,
} from "./search-filters.ts";
import { FilterContextBanner } from "./search-result-chrome.tsx";
import type { CardMetadata } from "../data/types.ts";
import { shouldStickToBottom } from "./chat-scroll.ts";

interface Props {
  base: string;
  /**
   * Optional manifest. When provided alongside an active filter URL state
   * (e.g. arriving at /chat from a filtered /search link), the citation
   * panel is post-filtered client-side using the same `cardMatchesFilters`
   * predicate the search island uses. The LLM still sees the full retrieval
   * set — this scopes the *displayed* sources only, mirroring search-side
   * behavior. PR #5 review F10.
   */
  cards?: CardMetadata[];
}

interface Message {
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  status: "streaming" | "done" | "error" | "abstained";
  errorMessage?: string;
  cached?: boolean;
}

const SUGGESTED_QUERIES = [
  "What does the FBI's 62-HQ-83894 file say about Roswell?",
  "Did Apollo 17 astronauts report any anomalies?",
  "Which incidents involved redacted location data?",
  "Show me Department of State cables on UAP encounters.",
  "What does the corpus say about UAP sightings near nuclear facilities?",
];

export default function ChatIsland({ base, cards }: Props) {
  const [config, setConfig] = useState<BYOKConfig>(() => loadBYOKConfig());
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"" | "RETRIEVING" | "GENERATING">("");
  const [showSettings, setShowSettings] = useState(false);
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  // Whether streamed deltas should keep auto-scrolling the transcript.
  // True at start; flips to false when the user scrolls up to re-read,
  // back to true when they return to the bottom. See chat-scroll.ts.
  const [stickToBottom, setStickToBottom] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Pull filter state from the URL on mount so a `/chat?agency=FBI&from=…`
  // link scopes the displayed citation list. LLM context is unaffected — the
  // worker's /api/retrieve has no filter awareness yet (vaivora F10).
  useEffect(() => {
    if (cards && cards.length > 0) {
      setFilters(parseFiltersFromQuery(window.location.search));
    }
  }, [cards]);

  // Build a card_id → CardMetadata lookup once for O(1) post-filter checks
  // against each citation. Empty Map when no manifest is provided — in that
  // case the post-filter is a no-op and behavior is identical to pre-PR.
  const cardsById = useMemo(() => {
    const m = new Map<string, CardMetadata>();
    if (cards) for (const c of cards) m.set(c.card_id, c);
    return m;
  }, [cards]);

  const filtersActive =
    filters.agencies.length > 0 ||
    filters.dateFrom !== "" ||
    filters.dateTo !== "" ||
    filters.redactedOnly;

  // Provider is recomputed when the config changes.
  const provider: LLMProvider = useMemo(() => {
    if (config.provider === "anthropic" && config.anthropicKey) {
      try {
        return new AnthropicBYOKProvider(config.anthropicKey, config.model);
      } catch (e) {
        // Fall through to anonymous if the key is invalid.
        console.warn("BYOK init failed; falling back to anonymous", e);
      }
    }
    return new AnthropicServerProvider();
  }, [config]);

  // Auto-scroll on new messages / streaming deltas, but only while the
  // user is at (or near) the bottom. If they've scrolled up to re-read
  // earlier content, leave them where they are — don't fight the read.
  useEffect(() => {
    if (stickToBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, stickToBottom]);

  const onTranscriptScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setStickToBottom(shouldStickToBottom(el.scrollHeight, el.scrollTop, el.clientHeight));
  };

  // Esc closes settings.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showSettings) {
        setShowSettings(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showSettings]);

  const submit = async (q: string) => {
    const query = q.trim();
    if (!query || busy) return;
    setBusy(true);
    setPhase("RETRIEVING");
    setInput("");

    const userMsg: Message = { role: "user", text: query, citations: [], status: "done" };
    const asstMsg: Message = { role: "assistant", text: "", citations: [], status: "streaming" };
    setMessages((prev) => [...prev, userMsg, asstMsg]);

    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      const stream = provider.stream(query, { abortSignal: ctrl.signal });
      let gotFirstText = false;
      for await (const chunk of stream as AsyncIterable<Chunk>) {
        applyChunk(chunk, () => {
          if (!gotFirstText && chunk.type === "text") {
            gotFirstText = true;
            setPhase("GENERATING");
          }
        });
        if (ctrl.signal.aborted) break;
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        appendErrorToLast(String(e?.message || e));
      }
    } finally {
      setBusy(false);
      setPhase("");
      finalizeLast();
      // Refocus input after the round-trip.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const applyChunk = (chunk: Chunk, sideEffect: () => void) => {
    sideEffect();
    setMessages((prev) => {
      const next = prev.slice();
      const idx = next.length - 1;
      const last = { ...next[idx] };
      switch (chunk.type) {
        case "citations":
          // Post-filter the citations against any active URL filter state so
          // the displayed source list matches the user's expectation from
          // /search. The model still grounded on the full retrieval set
          // — this scopes display only.
          last.citations = filtersActive
            ? chunk.passages.filter((p) => {
                const card = cardsById.get(p.card_id);
                return card ? cardMatchesFilters(card, filters) : true;
              })
            : chunk.passages;
          break;
        case "text":
          last.text = (last.text || "") + chunk.delta;
          break;
        case "done":
          last.status = chunk.abstained ? "abstained" : "done";
          last.cached = chunk.cached;
          break;
        case "error":
          last.status = "error";
          last.errorMessage = chunk.message;
          break;
      }
      next[idx] = last;
      return next;
    });
  };

  const appendErrorToLast = (msg: string) => {
    setMessages((prev) => {
      const next = prev.slice();
      const idx = next.length - 1;
      next[idx] = { ...next[idx], status: "error", errorMessage: msg };
      return next;
    });
  };

  const finalizeLast = () => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice();
      const idx = next.length - 1;
      if (next[idx].status === "streaming") {
        next[idx] = { ...next[idx], status: "done" };
      }
      return next;
    });
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit(input);
    }
  };

  const onSettingsChange = (c: BYOKConfig) => setConfig(c);

  return (
    <div class="flex flex-col h-[calc(100vh-220px)] min-h-[480px]">
      {/* Provider strip */}
      <div class="flex items-center justify-between border-b border-[color:var(--color-border)] pb-2 mb-3 text-[10px] font-mono uppercase tracking-[0.2em] text-[color:var(--color-text-dim)]">
        <span>
          PROVIDER:{" "}
          <span
            class={
              provider.isBYOK
                ? "text-[color:var(--color-signal-cyan)]"
                : "text-[color:var(--color-signal-green)]"
            }
          >
            {provider.name}
          </span>
          <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
          MODEL: <span class="text-[color:var(--color-text-bright)]">{provider.model}</span>
        </span>
        <button
          onClick={() => setShowSettings(true)}
          class="px-2 py-1 border border-[color:var(--color-border)] hover:border-[color:var(--color-signal-green)] hover:text-[color:var(--color-signal-green)] transition-colors"
          aria-label="Open chat settings (provider, model, BYOK key)"
        >
          <span aria-hidden="true">⚙ </span>SETTINGS
        </button>
      </div>

      {filtersActive && (
        <FilterContextBanner
          filters={filters}
          onClear={() => setFilters(EMPTY_FILTERS)}
        />
      )}

      {/* Messages area — aria-live="polite" so the streaming assistant
          response and phase indicator are announced to screen readers
          as new content arrives. role="log" is the standard pattern for
          a chat transcript that grows over time. The phase banner uses
          role="status" so RETRIEVING/GENERATING transitions are
          announced without being chatty about every text delta. */}
      <div
        ref={scrollRef}
        onScroll={onTranscriptScroll}
        role="log"
        aria-live="polite"
        aria-label="Chat transcript"
        class="flex-1 overflow-y-auto pr-1"
      >
        {messages.length === 0 && <EmptyState onPick={(q) => submit(q)} />}
        <ul class="space-y-5">
          {messages.map((m, i) => (
            <li key={i} class={m.role === "user" ? "flex justify-end" : ""}>
              {m.role === "user" ? (
                <UserMessage text={m.text} />
              ) : (
                <AssistantMessage msg={m} base={base} />
              )}
            </li>
          ))}
        </ul>
      </div>
      {/* Phase indicator sits OUTSIDE the role="log" container — nested
          live regions can double-announce on some screen readers
          (vaivora P1, 2026-05-12). Sibling placement keeps polite
          phase transitions distinct from transcript appends. */}
      {busy && (
        <p
          role="status"
          class="pi-loading text-[11px] uppercase tracking-[0.18em] mt-3"
        >
          {phase}<span class="pi-caret" aria-hidden="true"></span>
        </p>
      )}

      {/* Composer */}
      <div class="mt-3 border-t border-[color:var(--color-border)] pt-3">
        <label for="chat-input" class="sr-only">
          Question for the PURSUE corpus
        </label>
        <textarea
          id="chat-input"
          ref={inputRef}
          value={input}
          onInput={(e) => setInput((e.target as HTMLTextAreaElement).value)}
          onKeyDown={onKeyDown}
          placeholder="Ask the corpus a question…"
          rows={2}
          class="w-full font-mono text-sm resize-none"
          disabled={busy}
          autofocus
          aria-describedby="chat-send-hint"
        />
        <div class="flex items-center justify-between mt-2 text-[10px] font-mono uppercase tracking-[0.18em] text-[color:var(--color-text-faint)]">
          <span id="chat-send-hint">CMD/CTRL + ENTER TO SEND</span>
          <button
            onClick={() => submit(input)}
            disabled={busy || !input.trim()}
            aria-label={busy ? "Sending question" : "Send question"}
            class="px-3 py-1 border border-[color:var(--color-signal-green)] text-[color:var(--color-signal-green)] hover:bg-[color:var(--color-signal-green)]/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {busy ? "…" : "SEND"}
          </button>
        </div>
      </div>

      {showSettings && (
        <ChatSettingsPanel
          onClose={() => setShowSettings(false)}
          onChange={onSettingsChange}
        />
      )}
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div class="border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-4 pi-bracket relative scanlines-soft">
      <p class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-signal-green)] mb-3">
        // SAMPLE QUERIES
      </p>
      <ul class="space-y-1.5">
        {SUGGESTED_QUERIES.map((q) => (
          <li key={q}>
            <button
              onClick={() => onPick(q)}
              class="text-left w-full text-[13px] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-signal-cyan)] font-mono"
            >
              <span class="text-[color:var(--color-text-faint)] mr-2">›</span>
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UserMessage({ text }: { text: string }) {
  return (
    <div class="max-w-[80%] border-r-2 border-[color:var(--color-signal-green)] pr-3 text-right">
      <div class="text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-text-faint)] mb-1">
        QUERY
      </div>
      <div class="text-sm text-[color:var(--color-text-bright)] whitespace-pre-wrap">
        {text}
      </div>
    </div>
  );
}

function AssistantMessage({ msg, base }: { msg: Message; base: string }) {
  return (
    <div class="space-y-3">
      <div class="text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-text-faint)] flex items-center gap-2">
        <span class="text-[color:var(--color-signal-green)]">DOW://PURSUE</span>
        {msg.cached && <span class="text-[color:var(--color-signal-cyan)]">[CACHED]</span>}
        {msg.status === "abstained" && (
          <span class="text-[color:var(--color-signal-amber)]">[ABSTAINED]</span>
        )}
      </div>
      {msg.citations && msg.citations.length > 0 && (
        <CitationList citations={msg.citations} base={base} />
      )}
      <div class="font-mono text-sm leading-relaxed text-[color:var(--color-text-bright)] whitespace-pre-wrap">
        {segmentWithCitations(msg.text || "", msg.citations || [], base)}
        {msg.status === "streaming" && <span class="pi-caret"></span>}
      </div>
      {msg.status === "error" && msg.errorMessage && (
        <ErrorBlock message={msg.errorMessage} />
      )}
    </div>
  );
}

function CitationList({ citations, base }: { citations: Citation[]; base: string }) {
  return (
    <div class="border-l-2 border-[color:var(--color-border)] pl-3 space-y-2">
      <div class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]">
        SOURCES ({citations.length})
      </div>
      <ul class="space-y-2">
        {citations.map((c, i) => (
          <li key={`${c.card_id}-${c.page}`}>
            <a
              href={`${base}/card/${c.card_id}#page-${c.page}`}
              target="_blank"
              rel="noreferrer"
              class="block border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] hover:border-[color:var(--color-signal-cyan)] p-2 transition-colors"
            >
              <div class="text-[10px] font-mono uppercase tracking-[0.15em] text-[color:var(--color-text-faint)]">
                <span class="text-[color:var(--color-signal-cyan)]">[{i + 1}]</span>
                <span class="mx-2">·</span>
                <span class="text-[color:var(--color-signal-cyan)]">P{c.page}</span>
                <span class="mx-2">·</span>
                <span>SCORE {c.score.toFixed(2)}</span>
                <span class="mx-2">·</span>
                <span>{c.card_id.slice(0, 8)}</span>
              </div>
              <div class="text-[12px] text-[color:var(--color-text-bright)] mt-1 line-clamp-1">
                {c.title}
              </div>
              {c.snippet && (
                <p class="font-mono text-[11px] text-[color:var(--color-text-dim)] mt-1 line-clamp-3">
                  {c.snippet}
                </p>
              )}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
  const isRateLimit = /rate limit|too many|byok/i.test(message);
  const isBudget = /high traffic|budget|exceeded/i.test(message);
  return (
    <div
      role="alert"
      class="border border-[color:var(--color-signal-red)]/50 bg-[color:var(--color-signal-red)]/5 p-3 font-mono text-[12px]"
    >
      <div class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-signal-red)] mb-1">
        <span class="sr-only">Error: </span>[ERR]
      </div>
      <p class="text-[color:var(--color-text)]">{message}</p>
      {(isRateLimit || isBudget) && (
        <p class="text-[11px] text-[color:var(--color-text-dim)] mt-2">
          Tip: Open settings (top-right) and add an Anthropic API key to chat
          without limits. Your key never leaves the browser.
        </p>
      )}
    </div>
  );
}
