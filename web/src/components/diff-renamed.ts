/**
 * Byte-change evidence on a /diff RENAMED row (R7C.13).
 *
 * An alias row may carry the sha256 of the bytes on each side of the
 * rename plus the nature of the change (`data/card-aliases.json`'s optional
 * `old_byte_sha256` / `new_byte_sha256` / `change_nature`). This module is
 * the pure logic deciding what the row shows; `DiffRenamedSection.tsx` is
 * the thin JSX wrapper around it. A row without the evidence describes to
 * exactly today's row: the alias method and nothing else.
 */

import type { AliasEntry } from "../data/types.ts";

/** The optional evidence fields, camel-cased off an `AliasEntry`. */
export interface RenameEvidence {
  oldByteSha256?: string;
  newByteSha256?: string;
  changeNature?: string;
}

/** One link of an alias chain (`from` -> `to`), with its own nature when recorded. */
export interface RenameHop {
  from: string;
  to: string;
  changeNature?: string;
}

/** A hop as the RENAMED row lists it. */
export interface RenamedHopDisplay {
  from: string;
  to: string;
  /** The hop's own nature of change, or "unrecorded" when its alias row has none. */
  changeNature: string;
}

export interface RenamedRowDisplay {
  method: string;
  /** Nature of change, or null when the alias row doesn't record one. */
  changeNature: string | null;
  /** `old → new` byte shas (short for display, full for the tooltip), or null. */
  shaChange: { short: string; full: string } | null;
  /** Each hop of a chain whose hops could not be collapsed; absent otherwise. */
  hops?: RenamedHopDisplay[];
}

/** Pull the optional evidence off a raw alias row (absent fields stay absent). */
export function aliasEvidence(a: AliasEntry): RenameEvidence {
  const out: RenameEvidence = {};
  if (a.old_byte_sha256) out.oldByteSha256 = a.old_byte_sha256;
  if (a.new_byte_sha256) out.newByteSha256 = a.new_byte_sha256;
  if (a.change_nature) out.changeNature = a.change_nature;
  return out;
}

/** What a RENAMED row shows beyond its titles. */
export function describeRenamedRow(
  r: RenameEvidence & { method: string; hops?: RenameHop[] },
): RenamedRowDisplay {
  const { oldByteSha256: oldSha, newByteSha256: newSha } = r;
  const shaChange =
    oldSha || newSha
      ? {
          short: `${oldSha?.slice(0, 12) ?? "?"} → ${newSha?.slice(0, 12) ?? "?"}`,
          full: `${oldSha ?? "?"} → ${newSha ?? "?"}`,
        }
      : null;
  const display: RenamedRowDisplay = { method: r.method, changeNature: r.changeNature ?? null, shaChange };
  if (r.hops && r.hops.length > 0) {
    display.hops = r.hops.map((h) => ({ from: h.from, to: h.to, changeNature: h.changeNature ?? "unrecorded" }));
  }
  return display;
}
