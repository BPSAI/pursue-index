// BYOK config helpers — small wrappers around localStorage so we have one
// place that knows the keys, the validation, and the redact-for-display
// logic. Never serialize the raw key for any debug/log purpose.
//
// Storage keys are namespaced under `pursueindex.byok.*` to avoid colliding
// with anything else the site might want to put in localStorage later.

const KEY_PROVIDER = "pursueindex.byok.provider"; // "anonymous" | "anthropic"
const KEY_ANTHROPIC = "pursueindex.byok.anthropicKey";
const KEY_MODEL = "pursueindex.byok.model";

export type ProviderId = "anonymous" | "anthropic";

export interface BYOKConfig {
  provider: ProviderId;
  anthropicKey: string | null;
  model: string;
}

export const DEFAULT_MODEL = "claude-sonnet-4-6";
export const AVAILABLE_MODELS = ["claude-sonnet-4-6", "claude-opus-4-7"];

export function loadBYOKConfig(): BYOKConfig {
  if (typeof localStorage === "undefined") {
    return { provider: "anonymous", anthropicKey: null, model: DEFAULT_MODEL };
  }
  const provider = (localStorage.getItem(KEY_PROVIDER) || "anonymous") as ProviderId;
  const anthropicKey = localStorage.getItem(KEY_ANTHROPIC);
  const model = localStorage.getItem(KEY_MODEL) || DEFAULT_MODEL;
  return {
    provider: provider === "anthropic" ? "anthropic" : "anonymous",
    anthropicKey: anthropicKey || null,
    model: AVAILABLE_MODELS.includes(model) ? model : DEFAULT_MODEL,
  };
}

export function saveAnthropicKey(key: string): void {
  if (!isValidAnthropicKey(key)) throw new Error("Invalid Anthropic key shape");
  localStorage.setItem(KEY_ANTHROPIC, key);
  localStorage.setItem(KEY_PROVIDER, "anthropic");
}

export function clearAnthropicKey(): void {
  localStorage.removeItem(KEY_ANTHROPIC);
  localStorage.setItem(KEY_PROVIDER, "anonymous");
}

export function setProvider(p: ProviderId): void {
  localStorage.setItem(KEY_PROVIDER, p);
}

export function setModel(m: string): void {
  if (!AVAILABLE_MODELS.includes(m)) throw new Error("Unknown model: " + m);
  localStorage.setItem(KEY_MODEL, m);
}

/** Anthropic keys all start with sk-ant- and are >40 chars in practice. */
export function isValidAnthropicKey(key: string): boolean {
  return typeof key === "string" && /^sk-ant-[A-Za-z0-9_-]{20,}$/.test(key);
}

/** Show only the first 8 + last 4 chars of a key, for the settings UI. */
export function redactKey(key: string | null | undefined): string {
  if (!key) return "(none)";
  if (key.length <= 14) return "••••" + key.slice(-2);
  return key.slice(0, 8) + "…" + key.slice(-4);
}
