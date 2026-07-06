/**
 * Visual-review session tests (FTY-247).
 *
 * Covers activation semantics (idempotency + the remount revision), the fetch
 * override resolution, and the settle-tracking gate — all the runtime pieces the
 * deep-link route, the mock fetch, and the settle overlay depend on.
 */

import { registerVisualReviewPreset, __resetVisualReviewRegistry } from './registry';
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
  getVisualReviewCore,
  getVisualReviewFetchTick,
  recordVisualReviewServed,
  resolveVisualReviewFetch,
} from './session';
import type { VisualReviewPreset } from './types';

const SEEDED: VisualReviewPreset = {
  name: 'demo.populated',
  route: '/trends',
  settledPath: '/trends',
  theme: 'dark',
  responses: [
    {
      match: (ctx) => ctx.method === 'GET' && ctx.pathEnd.endsWith('/weight-entries'),
      body: [{ id: 'demo' }],
    },
    {
      match: (ctx) => ctx.pathEnd.endsWith('/with-status'),
      body: { detail: 'gone' },
      status: 410,
    },
  ],
};

beforeEach(() => {
  registerVisualReviewPreset(SEEDED);
});

afterEach(() => {
  __deactivateVisualReview();
  __resetVisualReviewRegistry();
});

describe('activateVisualReviewPreset', () => {
  it('returns ok:false and stays inert for an unregistered preset (fail closed)', () => {
    expect(activateVisualReviewPreset('never.registered', null).ok).toBe(false);
    expect(getVisualReviewCore().presetName).toBeNull();
  });

  it('activates a registered preset and reflects it in the core snapshot', () => {
    const res = activateVisualReviewPreset('demo.populated', 'light');
    expect(res).toEqual({ ok: true, changed: true });
    const core = getVisualReviewCore();
    expect(core.presetName).toBe('demo.populated');
    expect(core.route).toBe('/trends');
    expect(core.settledPath).toBe('/trends');
    expect(core.theme).toBe('light'); // the explicit param overrides the preset default
    expect(core.revision).toBe(1);
  });

  it('falls back to the preset default theme when none is passed', () => {
    activateVisualReviewPreset('demo.populated', null);
    expect(getVisualReviewCore().theme).toBe('dark');
  });

  it('bumps the revision on a real change but is idempotent for the same params', () => {
    activateVisualReviewPreset('demo.populated', 'dark');
    const first = getVisualReviewCore().revision;
    // Same name + theme → no bump (this is what stops the remount loop and tells
    // the route it is the post-remount pass that should navigate).
    expect(activateVisualReviewPreset('demo.populated', 'dark').changed).toBe(false);
    expect(getVisualReviewCore().revision).toBe(first);
    // A theme change is a real change → bump.
    expect(activateVisualReviewPreset('demo.populated', 'light').changed).toBe(true);
    expect(getVisualReviewCore().revision).toBe(first + 1);
  });
});

describe('resolveVisualReviewFetch', () => {
  const ctx = (pathEnd: string, method = 'GET') => ({
    url: `http://localhost/api${pathEnd}`,
    method,
    pathEnd: `/api${pathEnd}`,
  });

  it('returns null when no preset is active', () => {
    expect(resolveVisualReviewFetch(ctx('/weight-entries'))).toBeNull();
  });

  it('serves a matching override for the active preset', async () => {
    activateVisualReviewPreset('demo.populated', null);
    const res = resolveVisualReviewFetch(ctx('/weight-entries'));
    expect(res).not.toBeNull();
    expect(res?.status).toBe(200);
    await expect(res?.json()).resolves.toEqual([{ id: 'demo' }]);
  });

  it('honours a custom status on an override', () => {
    activateVisualReviewPreset('demo.populated', null);
    expect(resolveVisualReviewFetch(ctx('/with-status'))?.status).toBe(410);
  });

  it('returns null for an endpoint the active preset does not override (falls through)', () => {
    activateVisualReviewPreset('demo.populated', null);
    expect(resolveVisualReviewFetch(ctx('/profile'))).toBeNull();
  });
});

describe('recordVisualReviewServed (settle tracking gate)', () => {
  it('does nothing when no preset is active', () => {
    const before = getVisualReviewFetchTick();
    recordVisualReviewServed();
    expect(getVisualReviewFetchTick()).toBe(before);
  });

  it('bumps the fetch tick while a preset is active, and resets it on activation', () => {
    activateVisualReviewPreset('demo.populated', null);
    expect(getVisualReviewFetchTick()).toBe(0);
    recordVisualReviewServed();
    recordVisualReviewServed();
    expect(getVisualReviewFetchTick()).toBe(2);
  });
});
