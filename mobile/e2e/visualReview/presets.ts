/**
 * In-scope visual-review preset manifest (FTY-247).
 *
 * These are the presets reachable **purely through existing public navigation,
 * shared fixtures, and shared session/onboarding control** — no screen-owned
 * edits. Each registers itself through the registration API
 * ({@link registerVisualReviewPreset}), demonstrating that presets can be
 * contributed from a module *outside* the registry file. The per-screen seam
 * stories (FTY-262..268) register their sub-state presets the same way, from
 * their own lane, without touching this file.
 *
 * Sub-state presets that sit behind component-local `useState` (a sheet/mode/
 * step opened only by a press callback) are intentionally NOT here — reaching
 * them needs a screen-owned E2E seam, which is out of scope for FTY-247. Any
 * such name is unregistered and therefore fails closed (see the deep-link route).
 *
 * All fixtures are the synthetic constants already used by the E2E flows — no
 * real users, bodies, or logs.
 */

import { registerVisualReviewPreset } from './registry';
import type { VisualReviewFetchContext, VisualReviewResponse } from './types';
import {
  E2E_DAILY_SUMMARY,
  E2E_RESOLVE_ENTRY,
  E2E_RESOLVE_EVENT,
  E2E_RESOLVE_SUMMARY,
} from '../fixtures';

/** Match a GET request whose path ends with `suffix`. */
function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === 'GET' && ctx.pathEnd.endsWith(suffix);
}

/** An empty JSON array body (an empty list read). */
const EMPTY_LIST: VisualReviewResponse['body'] = [];

// ─── Today ────────────────────────────────────────────────────────────────────

// today.populated — a resolved multi-item day: the by-date feed carries the
// greek-yogurt+banana entry and the summary counts 245 kcal, so Today renders a
// full timeline and a consumed/target hero rather than the empty-day invite.
registerVisualReviewPreset({
  name: 'today.populated',
  route: '/',
  settledPath: '/',
  responses: [
    { match: get('/log-events/by-date'), body: [E2E_RESOLVE_ENTRY] },
    { match: get('/log-events'), body: [E2E_RESOLVE_EVENT] },
    { match: get('/daily-summary'), body: E2E_RESOLVE_SUMMARY },
  ],
});

// today.empty — the calm empty-day state: no entries, zero intake, full budget.
// Explicit empty overrides keep it hermetic regardless of any prior flow state
// in a shared binary.
registerVisualReviewPreset({
  name: 'today.empty',
  route: '/',
  settledPath: '/',
  responses: [
    { match: get('/log-events/by-date'), body: EMPTY_LIST },
    { match: get('/log-events'), body: EMPTY_LIST },
    { match: get('/daily-summary'), body: E2E_DAILY_SUMMARY },
  ],
});

// today.signed_out — the E2E session store hydrates a null session while this
// preset is active (see e2eSessionStore.load), so the auth gate renders the
// signed-out sign-in surface. Because the session is a pure function of the
// active preset (not an imperative sign-out), switching back to a signed-in
// preset reseeds the synthetic session at runtime — the state is not sticky. No
// fixtures: the sign-in screen needs no backend.
registerVisualReviewPreset({
  name: 'today.signed_out',
  route: '/',
  settledPath: '/signin',
  signedOut: true,
});

// ─── Trends ────────────────────────────────────────────────────────────────────

// trends.populated — the default E2E mock already serves a populated weight
// series and adherence range anchored to the requested window, so no overrides
// are needed; navigating to Trends renders the data-present cards.
registerVisualReviewPreset({
  name: 'trends.populated',
  route: '/trends',
  settledPath: '/trends',
});

// trends.empty — both the weight series and the adherence range come back empty
// so Trends renders its empty-state cards.
registerVisualReviewPreset({
  name: 'trends.empty',
  route: '/trends',
  settledPath: '/trends',
  responses: [
    { match: get('/weight-entries'), body: EMPTY_LIST },
    { match: get('/daily-summary/range'), body: EMPTY_LIST },
  ],
});

// ─── Weight (the weight trend on the Trends surface) ────────────────────────────

// weight.populated — the weight card with a synthetic series (the default mock).
registerVisualReviewPreset({
  name: 'weight.populated',
  route: '/trends',
  settledPath: '/trends',
});

// weight.empty — the weight card with no series (the log-weight empty state),
// while the adherence range keeps its default data.
registerVisualReviewPreset({
  name: 'weight.empty',
  route: '/trends',
  settledPath: '/trends',
  responses: [{ match: get('/weight-entries'), body: EMPTY_LIST }],
});

// ─── Settings ───────────────────────────────────────────────────────────────────

// settings.list — the settings route's top-level list. Profile, target, and the
// active goal come from the shared default fixtures.
registerVisualReviewPreset({
  name: 'settings.list',
  route: '/profile',
  settledPath: '/profile',
});
