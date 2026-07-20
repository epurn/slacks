/**
 * Client mirror of the backend saved-food matching rule
 * (`backend/app/normalization.py` → `normalize_text`, FTY-052). The backend
 * docstring names the client as the second home for this rule so a name
 * normalizes identically on both sides — the same rule FTY-406's
 * prior-correction lookup keys on.
 *
 * The rule, in order:
 *   1. Unicode NFKD decomposition (accents split into base + combining marks);
 *   2. drop the combining marks (Unicode category `Mn`), so `café` → `cafe`;
 *   3. case fold (lower-case);
 *   4. collapse every whitespace run to a single space, trimmed.
 *
 * Pure, deterministic, and idempotent. It is used only to decide whether a
 * typed name matches one of the user's own prior foods for the quick-add
 * default (FTY-408) — a UX hint; the authoritative resolution is the backend's
 * own `normalize_text` at estimate time. JS `toLowerCase` is a slightly weaker
 * fold than Python's `casefold` (e.g. `ß`), which only affects whether the hint
 * surfaces for such rare names, never what gets logged.
 */
export function normalizeText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{Mn}/gu, "")
    .toLowerCase()
    .split(/\s+/u)
    .filter((segment) => segment.length > 0)
    .join(" ");
}
