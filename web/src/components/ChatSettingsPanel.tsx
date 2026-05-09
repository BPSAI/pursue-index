import { useState } from "preact/hooks";
import {
  type BYOKConfig,
  type ProviderId,
  AVAILABLE_MODELS,
  DEFAULT_MODEL,
  clearAnthropicKey,
  isValidAnthropicKey,
  loadBYOKConfig,
  redactKey,
  saveAnthropicKey,
  setModel,
  setProvider,
} from "../lib/byok";

interface Props {
  onClose: () => void;
  onChange: (config: BYOKConfig) => void;
}

type Status =
  | { kind: "idle" }
  | { kind: "saved"; message: string }
  | { kind: "error"; message: string };

export default function ChatSettingsPanel({ onClose, onChange }: Props) {
  const [config, setConfig] = useState<BYOKConfig>(() => loadBYOKConfig());
  const [keyInput, setKeyInput] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const refresh = () => {
    const c = loadBYOKConfig();
    setConfig(c);
    onChange(c);
  };

  const onProvider = (p: ProviderId) => {
    setProvider(p);
    refresh();
    setStatus({ kind: "saved", message: `Provider set to ${p}` });
  };

  const onSaveKey = () => {
    try {
      saveAnthropicKey(keyInput.trim());
      setKeyInput("");
      refresh();
      setStatus({ kind: "saved", message: "Key saved. Provider set to BYOK." });
    } catch (e: any) {
      setStatus({ kind: "error", message: String(e?.message || e) });
    }
  };

  const onClearKey = () => {
    clearAnthropicKey();
    refresh();
    setStatus({ kind: "saved", message: "Key cleared. Reverted to anonymous." });
  };

  const onModel = (m: string) => {
    setModel(m);
    refresh();
    setStatus({ kind: "saved", message: `Model set to ${m}` });
  };

  return (
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        class="w-full max-w-lg mx-4 border border-[color:var(--color-border)] bg-[color:var(--color-bg-deep)] p-5 space-y-5 font-mono text-sm pi-bracket"
        onClick={(e) => e.stopPropagation()}
      >
        <div class="flex items-center justify-between">
          <h2 class="text-[color:var(--color-text-bright)] uppercase tracking-[0.2em] text-xs">
            CHAT // SETTINGS
          </h2>
          <button
            onClick={onClose}
            class="text-[color:var(--color-text-faint)] hover:text-[color:var(--color-signal-red)] uppercase text-[10px] tracking-[0.18em]"
            aria-label="Close settings"
          >
            ESC
          </button>
        </div>

        {/* Provider */}
        <section class="space-y-2">
          <h3 class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]">
            Provider
          </h3>
          <div class="grid grid-cols-2 gap-2">
            <button
              onClick={() => onProvider("anonymous")}
              class={`px-3 py-2 border text-left text-xs transition-colors ${
                config.provider === "anonymous"
                  ? "border-[color:var(--color-signal-green)] text-[color:var(--color-signal-green)] bg-[color:var(--color-signal-green)]/10"
                  : "border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-text-bright)]/40"
              }`}
            >
              <div class="text-[11px] uppercase tracking-wider">anonymous</div>
              <div class="text-[10px] text-[color:var(--color-text-faint)] mt-0.5">
                server-funded · 5/day · sonnet 4.6
              </div>
            </button>
            <button
              onClick={() => onProvider("anthropic")}
              disabled={!config.anthropicKey}
              title={config.anthropicKey ? undefined : "Add an Anthropic key first"}
              class={`px-3 py-2 border text-left text-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                config.provider === "anthropic"
                  ? "border-[color:var(--color-signal-cyan)] text-[color:var(--color-signal-cyan)] bg-[color:var(--color-signal-cyan)]/10"
                  : "border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-text-bright)]/40"
              }`}
            >
              <div class="text-[11px] uppercase tracking-wider">BYOK</div>
              <div class="text-[10px] text-[color:var(--color-text-faint)] mt-0.5">
                your key · no rate limit · model choice
              </div>
            </button>
          </div>
        </section>

        {/* Model */}
        <section class="space-y-2">
          <h3 class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]">
            Model {config.provider === "anonymous" && <span class="text-[color:var(--color-text-faint)]">(locked in anonymous mode)</span>}
          </h3>
          <div class="flex flex-wrap gap-2">
            {AVAILABLE_MODELS.map((m) => (
              <button
                key={m}
                disabled={config.provider === "anonymous" && m !== DEFAULT_MODEL}
                onClick={() => onModel(m)}
                class={`px-2 py-1 text-[11px] border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                  config.model === m
                    ? "border-[color:var(--color-signal-green)] text-[color:var(--color-signal-green)]"
                    : "border-[color:var(--color-border)] text-[color:var(--color-text-dim)] hover:border-[color:var(--color-text-bright)]/40"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </section>

        {/* Anthropic key */}
        <section class="space-y-2">
          <h3 class="text-[10px] uppercase tracking-[0.2em] text-[color:var(--color-text-faint)]">
            Anthropic API key
          </h3>
          {config.anthropicKey ? (
            <div class="flex items-center justify-between gap-2 border border-[color:var(--color-border)] px-3 py-2 bg-[color:var(--color-bg-elevated)]">
              <span class="text-[color:var(--color-signal-cyan)] text-xs">
                {redactKey(config.anthropicKey)}
              </span>
              <button
                onClick={onClearKey}
                class="text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-signal-red)] hover:text-[color:var(--color-text-bright)]"
              >
                CLEAR
              </button>
            </div>
          ) : (
            <div class="space-y-2">
              <div class="flex gap-2">
                <input
                  type={showKey ? "text" : "password"}
                  value={keyInput}
                  onInput={(e) => setKeyInput((e.target as HTMLInputElement).value)}
                  placeholder="sk-ant-…"
                  class="flex-1 font-mono text-xs"
                  autoComplete="off"
                  spellcheck={false}
                />
                <button
                  onClick={() => setShowKey((s) => !s)}
                  class="px-2 text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-text-dim)] hover:text-[color:var(--color-text-bright)] border border-[color:var(--color-border)]"
                >
                  {showKey ? "HIDE" : "SHOW"}
                </button>
                <button
                  onClick={onSaveKey}
                  disabled={!isValidAnthropicKey(keyInput.trim())}
                  class="px-3 text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-signal-green)] hover:text-[color:var(--color-text-bright)] border border-[color:var(--color-signal-green)] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  SAVE
                </button>
              </div>
            </div>
          )}
          <p class="text-[10px] leading-relaxed text-[color:var(--color-text-faint)]">
            Your key never leaves the browser. We do not log, proxy, or
            store it on our servers — the request goes directly from your
            browser to api.anthropic.com.
          </p>
        </section>

        {status.kind !== "idle" && (
          <p
            class={`text-[11px] font-mono ${
              status.kind === "error"
                ? "text-[color:var(--color-signal-red)]"
                : "text-[color:var(--color-signal-green)]"
            }`}
          >
            {status.message}
          </p>
        )}
      </div>
    </div>
  );
}
