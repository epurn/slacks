/**
 * Visual-review registry + deep-link parsing tests (FTY-247).
 *
 * Covers the registration API (the join contract FTY-262..268 plug into) and the
 * fail-closed parsing of the `preset` / `theme` deep-link params.
 */

import {
  registerVisualReviewPreset,
  getVisualReviewPreset,
  listVisualReviewPresetNames,
  parseVisualReviewParams,
  __resetVisualReviewRegistry,
} from './registry';
import type { VisualReviewPreset } from './types';

const PRESET: VisualReviewPreset = {
  name: 'demo.state',
  route: '/',
  settledPath: '/',
};

afterEach(() => {
  __resetVisualReviewRegistry();
});

describe('registerVisualReviewPreset', () => {
  it('registers a preset that is then resolvable by name', () => {
    expect(getVisualReviewPreset('demo.state')).toBeUndefined();
    registerVisualReviewPreset(PRESET);
    expect(getVisualReviewPreset('demo.state')).toBe(PRESET);
  });

  it('lets a later registration replace an earlier one by name (seam override)', () => {
    registerVisualReviewPreset(PRESET);
    const replacement: VisualReviewPreset = { ...PRESET, route: '/trends' };
    registerVisualReviewPreset(replacement);
    expect(getVisualReviewPreset('demo.state')).toBe(replacement);
  });

  it('lists registered names sorted', () => {
    registerVisualReviewPreset({ ...PRESET, name: 'b.two' });
    registerVisualReviewPreset({ ...PRESET, name: 'a.one' });
    expect(listVisualReviewPresetNames()).toEqual(['a.one', 'b.two']);
  });

  it('throws on an empty preset name (a loud programming error)', () => {
    expect(() =>
      registerVisualReviewPreset({ ...PRESET, name: '' }),
    ).toThrow(/name is required/);
  });

  it('returns undefined for an unregistered name (fail-closed lookup)', () => {
    expect(getVisualReviewPreset('never.registered')).toBeUndefined();
  });
});

describe('parseVisualReviewParams', () => {
  it('parses a preset name and a light/dark theme', () => {
    expect(parseVisualReviewParams({ preset: 'today.populated', theme: 'dark' })).toEqual(
      { preset: 'today.populated', theme: 'dark' },
    );
    expect(parseVisualReviewParams({ preset: 'trends.empty', theme: 'light' })).toEqual(
      { preset: 'trends.empty', theme: 'light' },
    );
  });

  it('drops an unknown/invalid theme value to null (falls back to the preset default)', () => {
    expect(parseVisualReviewParams({ preset: 'x', theme: 'sepia' }).theme).toBeNull();
    expect(parseVisualReviewParams({ preset: 'x', theme: 'DARK' }).theme).toBeNull();
    expect(parseVisualReviewParams({ preset: 'x' }).theme).toBeNull();
  });

  it('treats a blank or missing preset as null', () => {
    expect(parseVisualReviewParams({ preset: '   ' }).preset).toBeNull();
    expect(parseVisualReviewParams({}).preset).toBeNull();
  });

  it('takes the first value when a param arrives as an array', () => {
    expect(
      parseVisualReviewParams({ preset: ['today.empty', 'ignored'], theme: ['light'] }),
    ).toEqual({ preset: 'today.empty', theme: 'light' });
  });
});
