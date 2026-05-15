import type { Manifest } from "../data/types";

interface Props {
  // Chronologically-sorted snapshot filenames (oldest → newest).
  index: string[];
  // Loaded snapshot manifests keyed by filename (lazy; may be partial).
  loaded: Record<string, Manifest>;
  // The synthetic "@current" entry that represents latest.json.
  currentFilename: string;
  currentManifest: Manifest;
  // Currently selected pair (filenames). May include the @current sentinel.
  selectedFrom: string | null;
  selectedTo: string | null;
  // Click handler: receives a filename, sets right=that, left=its prior.
  onJump: (right: string) => void;
}

function shaPrefix(filename: string): string {
  return filename.replace(/\.json$/i, "").slice(0, 8);
}

function dateLabel(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

/**
 * Small horizontal strip above the diff body. One tick per snapshot
 * plus a special "@current" terminal tick on the right edge. Clicking
 * a tick sets the right selector to that snapshot (the diff-pair
 * jumps to "what changed when this snapshot landed"). Hover surfaces
 * the snapshot's sha, fetched_at date, and card count.
 *
 * Aesthetic choices match the rest of the terminal lockup: small
 * uppercase mono labels, signal-cyan for the current selection,
 * faint dots for unselected, no animations.
 */
export default function DiffTimeline({
  index,
  loaded,
  currentFilename,
  currentManifest,
  selectedFrom,
  selectedTo,
  onJump,
}: Props) {
  if (index.length === 0) return null;

  const allFilenames = [...index, currentFilename];

  return (
    <nav
      aria-label="Snapshot timeline"
      class="border border-[color:var(--color-border)] bg-[color:var(--color-bg)]/40 p-3"
    >
      <ol class="flex items-center gap-1 overflow-x-auto pb-1">
        {allFilenames.map((f, i) => {
          const isCurrent = f === currentFilename;
          const m = isCurrent ? currentManifest : loaded[f];
          const isSelectedTo = f === selectedTo;
          const isSelectedFrom = f === selectedFrom;
          const isSelected = isSelectedTo || isSelectedFrom;

          const tickColor = isSelectedTo
            ? "var(--color-signal-cyan)"
            : isSelectedFrom
              ? "var(--color-signal-amber)"
              : "var(--color-text-faint)";

          const tooltip = [
            isCurrent ? "CURRENT" : shaPrefix(f),
            m ? dateLabel(m.fetched_at) : "(not loaded)",
            m ? `${m.cards.length} cards` : "",
          ].filter(Boolean).join(" · ");

          return (
            <li class="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onJump(f)}
                title={tooltip}
                aria-label={`Jump to ${isCurrent ? "current" : shaPrefix(f)}`}
                class={`relative h-2 w-2 rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-signal-cyan)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--color-bg)]`}
                style={`background: ${tickColor}; box-shadow: ${isSelected ? `0 0 8px ${tickColor}` : "none"}`}
              />
              {i < allFilenames.length - 1 && (
                <span
                  aria-hidden="true"
                  class="inline-block w-6 h-px"
                  style="background: var(--color-border-bright);"
                />
              )}
            </li>
          );
        })}
      </ol>
      <p class="font-mono text-[10px] uppercase tracking-[0.18em] text-[color:var(--color-text-faint)] pt-2">
        {index.length + 1} snapshots
        <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
        <span class="text-[color:var(--color-signal-amber)]">●</span> from
        <span class="mx-2 text-[color:var(--color-text-faint)]">·</span>
        <span class="text-[color:var(--color-signal-cyan)]">●</span> to (click any tick to jump)
      </p>
    </nav>
  );
}
