/**
 * Tests for the root AppearanceProvider (FTY-102).
 *
 * The provider must hydrate the persisted Light / Dark / System preference on
 * boot and drive the live theme from it, and expose a setter that switches the
 * theme in place — the wiring the Settings screen relies on so its Appearance
 * control is not a dead control.
 */

import React, { useEffect } from 'react';
import { act, create } from 'react-test-renderer';

import { AppearanceProvider, useAppearanceController } from '@/state/appearance';
import { useTheme } from '@/theme';
import type { AppSettingsStore } from '@/state/appSettings';
import type { ColorSchemeOverride } from '@/theme';

function mockStore(initial: ColorSchemeOverride): AppSettingsStore {
  let appearance = initial;
  return {
    getAppearance: jest.fn(async () => appearance),
    setAppearance: jest.fn(async (v: ColorSchemeOverride) => {
      appearance = v;
    }),
  };
}

/** Captures the live scheme and the appearance setter via effects. */
function Probe({
  onScheme,
  onSetter,
}: {
  onScheme: (scheme: 'light' | 'dark') => void;
  onSetter: (set: (v: ColorSchemeOverride) => void) => void;
}): null {
  const { scheme } = useTheme();
  const { setAppearance } = useAppearanceController();
  useEffect(() => {
    onScheme(scheme);
    onSetter(setAppearance);
  });
  return null;
}

describe('AppearanceProvider', () => {
  it('hydrates the persisted preference and drives the live theme', async () => {
    let scheme: 'light' | 'dark' = 'light';
    await act(async () => {
      create(
        <AppearanceProvider store={mockStore('dark')}>
          <Probe onScheme={(s) => (scheme = s)} onSetter={() => {}} />
        </AppearanceProvider>,
      );
    });
    expect(scheme).toBe('dark');
  });

  it('switches the live theme when setAppearance is called', async () => {
    let scheme: 'light' | 'dark' = 'light';
    let setter: (v: ColorSchemeOverride) => void = () => {};
    await act(async () => {
      create(
        <AppearanceProvider store={mockStore('light')}>
          <Probe
            onScheme={(s) => (scheme = s)}
            onSetter={(set) => (setter = set)}
          />
        </AppearanceProvider>,
      );
    });
    expect(scheme).toBe('light');

    await act(async () => {
      setter('dark');
    });
    expect(scheme).toBe('dark');
  });
});
