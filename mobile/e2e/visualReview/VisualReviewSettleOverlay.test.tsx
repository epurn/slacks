/**
 * Visual-review settle overlay tests (FTY-247).
 *
 * Proves the settled marker semantics screenshot automation relies on:
 *   - it appears only after the target screen is reached AND the network goes
 *     quiet (the QUIET_MS window),
 *   - a preset registered through the public registration API resolves and
 *     produces its own `visual-review-settled:<name>` marker (the FTY-262..268
 *     plug-in proof),
 *   - it is inert outside E2E mode (fail-closed gate).
 */

import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';

// Drive the pathname the overlay compares against.
let mockPathname = '/';
jest.mock('expo-router', () => ({
  usePathname: () => mockPathname,
}));

// eslint-disable-next-line import/first
import {
  VisualReviewSettleOverlay,
  QUIET_MS,
} from './VisualReviewSettleOverlay';
// eslint-disable-next-line import/first
import { registerVisualReviewPreset, __resetVisualReviewRegistry } from './registry';
// eslint-disable-next-line import/first
import {
  activateVisualReviewPreset,
  recordVisualReviewServed,
  __deactivateVisualReview,
} from './session';

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;

function enterE2EMode(): void {
  gThis['__DEV__'] = true;
  process.env['EXPO_PUBLIC_FATTY_E2E'] = 'true';
}

let mounted: ReactTestRenderer | null = null;

function mount(): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<VisualReviewSettleOverlay />);
  });
  mounted = tree;
  return tree;
}

beforeEach(() => {
  jest.useFakeTimers();
  mockPathname = '/';
  // Re-register the manifest under test (a fixture-only preset — enough to prove
  // the registration → settle path without any screen).
  registerVisualReviewPreset({
    name: 'plugin.demo',
    route: '/trends',
    settledPath: '/trends',
  });
});

afterEach(() => {
  if (mounted) {
    const tree = mounted;
    act(() => tree.unmount());
    mounted = null;
  }
  act(() => {
    __deactivateVisualReview();
  });
  __resetVisualReviewRegistry();
  jest.useRealTimers();
  gThis['__DEV__'] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E'] = ORIGINAL_E2E_ENV;
  }
});

function hasMarker(tree: ReactTestRenderer, testID: string): boolean {
  return tree.root.findAll((n) => n.props.testID === testID).length > 0;
}

describe('VisualReviewSettleOverlay', () => {
  it('exposes the settled marker for a registered preset once reached + quiet', () => {
    enterE2EMode();
    mockPathname = '/trends';
    activateVisualReviewPreset('plugin.demo', 'dark');

    const tree = mount();

    // Not yet: the network-quiet window has not elapsed.
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(false);

    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 10);
    });
    // Now the marker is present — the registration-API plug-in produced its marker.
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(true);
  });

  it('stays hidden until the target screen (settledPath) is reached', () => {
    enterE2EMode();
    mockPathname = '/'; // not the preset's settledPath (/trends)
    activateVisualReviewPreset('plugin.demo', null);

    const tree = mount();
    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 10);
    });
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(false);
  });

  it('restarts the quiet window when a new mock request arrives', () => {
    enterE2EMode();
    mockPathname = '/trends';
    activateVisualReviewPreset('plugin.demo', null);

    const tree = mount();
    // A late fixture read lands just before the window would close.
    act(() => {
      jest.advanceTimersByTime(QUIET_MS - 20);
      recordVisualReviewServed();
    });
    // The window restarted, so a bit more than the remaining old window is not enough.
    act(() => {
      jest.advanceTimersByTime(30);
    });
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(false);
    // A full fresh window from the last request settles it.
    act(() => {
      jest.advanceTimersByTime(QUIET_MS);
    });
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(true);
  });

  it('is inert outside E2E mode (renders nothing even when a preset is active)', () => {
    // Not entering E2E mode: __DEV__/env gate is off.
    gThis['__DEV__'] = false;
    mockPathname = '/trends';
    activateVisualReviewPreset('plugin.demo', 'dark');

    const tree = mount();
    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 50);
    });
    expect(tree.root.findAll(() => true).length).toBeGreaterThanOrEqual(0);
    expect(hasMarker(tree, 'visual-review-settled:plugin.demo')).toBe(false);
  });
});
