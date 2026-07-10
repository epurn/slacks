/**
 * Settings sub-state visual-review seam tests (FTY-267).
 *
 * Covers the join-contract half owned by this lane: the three sub-state presets
 * are registered through FTY-247's public API (not the shared registry/manifest
 * files), the sub-state hook maps each registered preset name to the right
 * sub-state, and the whole seam is inert outside E2E mode — the acceptance
 * criterion that it must be "proven inert in release/non-E2E builds by a test".
 */

import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';

import {
  useSettingsVisualReviewSubState,
  type SettingsVisualReviewSubState,
} from './visualReviewPresets';
// Importing the barrel also imports FTY-247's own manifest (`presets.ts`) as a
// side effect, so `getVisualReviewPreset` here can resolve both that manifest's
// names and this module's settings sub-state names.
import { getVisualReviewPreset } from '@/e2e/visualReview';
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from '@/e2e/visualReview/session';

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;

function enterE2EMode(): void {
  gThis['__DEV__'] = true;
  process.env['EXPO_PUBLIC_FATTY_E2E'] = 'true';
}

function exitE2EMode(): void {
  gThis['__DEV__'] = false;
}

afterEach(() => {
  act(() => {
    __deactivateVisualReview();
  });
  gThis['__DEV__'] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E'] = ORIGINAL_E2E_ENV;
  }
});

/** Mount the hook and read its current value via a tiny probe component. */
function readSubState(): SettingsVisualReviewSubState | null {
  let value: SettingsVisualReviewSubState | null = null;
  function Probe() {
    value = useSettingsVisualReviewSubState();
    return null;
  }
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(React.createElement(Probe));
  });
  act(() => tree.unmount());
  return value;
}

describe('settings sub-state preset registration', () => {
  it('registers settings.goal_edit / settings.body_edit / settings.appearance via the FTY-247 API', () => {
    for (const name of [
      'settings.goal_edit',
      'settings.body_edit',
      'settings.formula_edit',
      'settings.appearance',
      'settings.target_override',
    ]) {
      const preset = getVisualReviewPreset(name);
      expect(preset).toBeDefined();
      expect(preset?.route).toBe('/profile');
      expect(preset?.settledPath).toBe('/profile');
    }
  });

  it('registers settings.target_override with a synthetic user-source target fixture', () => {
    const response = getVisualReviewPreset('settings.target_override')?.responses?.find((r) =>
      r.match({
        url: 'https://api.example.test/api/target',
        method: 'GET',
        pathEnd: '/target',
      }),
    );

    expect(response).toBeDefined();
    expect((response?.body as { calories?: { source?: string } }).calories?.source).toBe(
      'user',
    );
  });
});

describe('useSettingsVisualReviewSubState', () => {
  it('maps settings.goal_edit to goal_edit', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.goal_edit', null);
    expect(readSubState()).toBe('goal_edit');
  });

  it('maps settings.body_edit to body_edit', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.body_edit', null);
    expect(readSubState()).toBe('body_edit');
  });

  it('maps settings.formula_edit to formula_edit', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.formula_edit', null);
    expect(readSubState()).toBe('formula_edit');
  });

  it('maps settings.appearance to appearance', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.appearance', null);
    expect(readSubState()).toBe('appearance');
  });

  it('is null when no preset is active', () => {
    enterE2EMode();
    expect(readSubState()).toBeNull();
  });

  it('is null for an unrelated active preset (e.g. settings.list)', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.list', null);
    expect(readSubState()).toBeNull();
  });

  it('is null for settings.target_override because that preset only installs a target fixture', () => {
    enterE2EMode();
    activateVisualReviewPreset('settings.target_override', null);
    expect(readSubState()).toBeNull();
  });

  it('is inert outside E2E mode, even with a matching preset active (release-build proof)', () => {
    // A preset can be activated directly (this call itself carries no E2E gate —
    // only the deep-link route and this hook do), so this proves the hook's own
    // `isE2EMode()` check is load-bearing rather than piggybacking on some other
    // gate.
    exitE2EMode();
    activateVisualReviewPreset('settings.formula_edit', null);
    expect(readSubState()).toBeNull();
  });
});
