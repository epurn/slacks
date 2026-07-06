/**
 * Visual-review runtime session (FTY-247).
 *
 * Holds the *currently active* preset and drives the three runtime seams the
 * visual-review mode needs, all behind the `isE2EMode()` gate its callers apply:
 *
 *   1. **Fetch overrides** — {@link resolveVisualReviewFetch} answers the seeded
 *      endpoints for the active preset before the default E2E mock, so a state
 *      is reachable with synthetic data and no live backend.
 *   2. **Remount signal** — activating a preset bumps a `revision` the root
 *      layout keys its navigator subtree on, forcing the target screen to remount
 *      and refetch with the new fixtures in place (no stale data from a screen
 *      that mounted before activation).
 *   3. **Settle tracking** — every mock request bumps a `fetchTick` while a
 *      preset is active, so the settle overlay can wait for the target screen to
 *      go network-quiet before exposing its screenshot marker.
 *
 * This module is plain module state with two tiny subscribe/getSnapshot pairs
 * (one low-frequency "core" channel, one high-frequency "fetch" channel) so
 * React can consume it via `useSyncExternalStore` without re-rendering the whole
 * app on every fixture request.
 */

import { getVisualReviewPreset } from './registry';
import type {
  VisualReviewFetchContext,
  VisualReviewPreset,
} from './types';

// ─── Core state (low-frequency: changes only on activate/deactivate) ─────────

/** Immutable snapshot of the active preset, or the inert default. */
export interface VisualReviewCoreSnapshot {
  readonly presetName: string | null;
  readonly route: string | null;
  readonly settledPath: string | null;
  readonly theme: 'light' | 'dark' | null;
  readonly signedOut: boolean;
  /** Bumped on each activation; the root layout keys its subtree on this to force a remount. */
  readonly revision: number;
}

const INERT_CORE: VisualReviewCoreSnapshot = {
  presetName: null,
  route: null,
  settledPath: null,
  theme: null,
  signedOut: false,
  revision: 0,
};

let activePreset: VisualReviewPreset | null = null;
let activeTheme: 'light' | 'dark' | null = null;
let revision = 0;

let coreSnapshot: VisualReviewCoreSnapshot = INERT_CORE;
const coreListeners = new Set<() => void>();

function rebuildCore(): void {
  coreSnapshot = activePreset
    ? {
        presetName: activePreset.name,
        route: activePreset.route,
        settledPath: activePreset.settledPath,
        theme: activeTheme,
        signedOut: activePreset.signedOut ?? false,
        revision,
      }
    : { ...INERT_CORE, revision };
}

function emitCore(): void {
  rebuildCore();
  for (const l of coreListeners) l();
}

export function subscribeVisualReviewCore(listener: () => void): () => void {
  coreListeners.add(listener);
  return () => coreListeners.delete(listener);
}

export function getVisualReviewCore(): VisualReviewCoreSnapshot {
  return coreSnapshot;
}

/**
 * True when the active preset requests the signed-out surface. The E2E session
 * store reads this so the session it hydrates is a pure function of the active
 * preset: a signed-out preset loads a `null` session, every other preset loads
 * the synthetic one. Because the root layout remounts the `SessionProvider` on
 * each activation (keyed on the revision), switching *from* the signed-out
 * preset back to a signed-in preset reseeds the session at runtime — no rebuild
 * and no order dependence. Defaults to `false` when no preset is active, so the
 * normal E2E flows always boot signed in.
 */
export function isActiveVisualReviewPresetSignedOut(): boolean {
  return activePreset?.signedOut ?? false;
}

// ─── Fetch tick (high-frequency: bumped on every mock request while active) ──

let fetchTick = 0;
const fetchListeners = new Set<() => void>();

export function subscribeVisualReviewFetch(listener: () => void): () => void {
  fetchListeners.add(listener);
  return () => fetchListeners.delete(listener);
}

export function getVisualReviewFetchTick(): number {
  return fetchTick;
}

/**
 * Record that the mock fetch answered a request. Bumps the fetch tick so the
 * settle overlay's network-quiet timer restarts. No-op when no preset is active,
 * so it costs nothing during the normal E2E flows (which never activate a
 * preset).
 */
export function recordVisualReviewServed(): void {
  if (!activePreset) return;
  fetchTick += 1;
  for (const l of fetchListeners) l();
}

// ─── Activation ──────────────────────────────────────────────────────────────

/** Outcome of an activation attempt. */
export interface VisualReviewActivation {
  /** True when the name was registered and is now active. */
  readonly ok: boolean;
  /**
   * True when this call bumped the revision (a real state change). The deep-link
   * route uses this to know whether a navigator remount is incoming: on the
   * bumping call it waits, and on the post-remount idempotent call (`changed:
   * false`) it performs the navigation — the remount having already put the
   * seeded fixtures in place before the target screen mounts.
   */
  readonly changed: boolean;
}

/**
 * Activate a registered preset, optionally forcing a theme. `ok: false` when the
 * name is not registered (the caller renders the fail-closed error marker).
 *
 * Idempotent: re-activating the exact same preset + theme does NOT bump the
 * revision (`changed: false`), which both stops the remount from looping and
 * signals the route that it is the post-remount pass that should now navigate.
 */
export function activateVisualReviewPreset(
  name: string,
  theme: 'light' | 'dark' | null,
): VisualReviewActivation {
  const preset = getVisualReviewPreset(name);
  if (!preset) return { ok: false, changed: false };

  const resolvedTheme = theme ?? preset.theme ?? null;
  if (activePreset?.name === name && activeTheme === resolvedTheme) {
    return { ok: true, changed: false };
  }

  activePreset = preset;
  activeTheme = resolvedTheme;
  fetchTick = 0;
  revision += 1;
  emitCore();
  // Reset the fetch channel too so a subscriber mounted before activation sees
  // the fresh baseline.
  for (const l of fetchListeners) l();
  return { ok: true, changed: true };
}

/** Test-only: clear the active preset and reset counters back to inert. */
export function __deactivateVisualReview(): void {
  activePreset = null;
  activeTheme = null;
  revision = 0;
  fetchTick = 0;
  emitCore();
  for (const l of fetchListeners) l();
}

// ─── Fetch resolution ─────────────────────────────────────────────────────────

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Answer a request from the active preset's fixtures, or `null` to fall through
 * to the default E2E mock. Called at the top of the E2E mock fetch, so a preset
 * can override just the endpoints it cares about (e.g. Today's day feed) while
 * leaving the rest (profile, target) on the shared defaults.
 */
export function resolveVisualReviewFetch(
  ctx: VisualReviewFetchContext,
): Response | null {
  const responses = activePreset?.responses;
  if (!responses) return null;
  for (const r of responses) {
    if (r.match(ctx)) {
      const body = typeof r.body === 'function' ? r.body(ctx) : r.body;
      return jsonResponse(body, r.status ?? 200);
    }
  }
  return null;
}
