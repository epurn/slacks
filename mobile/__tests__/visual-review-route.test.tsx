/**
 * Visual-review deep-link route tests (FTY-247).
 *
 * Proves the fail-closed gate and the preset dispatch for `app/__visual-review`:
 *   - inert outside E2E mode (release build path),
 *   - a deterministic error marker for an unknown preset (never a real route),
 *   - a known preset activates the runtime session.
 *
 * Lives under __tests__/ rather than beside the route in app/: everything under
 * app/ is an expo-router route (a recursive require.context), so a *.test.tsx
 * there would be bundled as a route and its top-level jest.fn() would crash the
 * E2E dev-client build (see __tests__/profile-route.test.tsx).
 */

import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';

let mockParams: { preset?: string | string[]; theme?: string | string[] } = {};
jest.mock('expo-router', () => ({
  useLocalSearchParams: () => mockParams,
  usePathname: () => '/',
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
  useRootNavigationState: () => ({ key: 'root' }),
}));

// eslint-disable-next-line import/first
import VisualReviewRoute from '@/app/__visual-review';
// The barrel import (transitively via the route) registers the in-scope manifest.
// eslint-disable-next-line import/first
import {
  getVisualReviewCore,
  __deactivateVisualReview,
} from '@/e2e/visualReview/session';

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

function setE2E(on: boolean): void {
  gThis['__DEV__'] = on;
  if (on) {
    process.env['EXPO_PUBLIC_SLACKS_E2E'] = 'true';
  } else {
    delete process.env['EXPO_PUBLIC_SLACKS_E2E'];
  }
}

afterEach(() => {
  __deactivateVisualReview();
  mockParams = {};
  gThis['__DEV__'] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_SLACKS_E2E'];
  } else {
    process.env['EXPO_PUBLIC_SLACKS_E2E'] = ORIGINAL_E2E_ENV;
  }
});

function render(): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<VisualReviewRoute />);
  });
  return tree;
}

function hasMarker(tree: ReactTestRenderer, testID: string): boolean {
  return tree.root.findAll((n) => n.props.testID === testID).length > 0;
}

describe('visual-review route', () => {
  it('is inert outside E2E mode and does not activate any preset', () => {
    setE2E(false);
    mockParams = { preset: 'today.populated', theme: 'dark' };
    const tree = render();
    expect(hasMarker(tree, 'visual-review-inert')).toBe(true);
    expect(getVisualReviewCore().presetName).toBeNull();
  });

  it('fails closed with a deterministic error marker for an unknown preset', () => {
    setE2E(true);
    mockParams = { preset: 'no.such.preset' };
    const tree = render();
    expect(hasMarker(tree, 'visual-review-error')).toBe(true);
    // No real route seeded.
    expect(getVisualReviewCore().presetName).toBeNull();
  });

  it('activates a known preset in E2E mode', () => {
    setE2E(true);
    mockParams = { preset: 'today.populated', theme: 'light' };
    const tree = render();
    expect(hasMarker(tree, 'visual-review-activating:today.populated')).toBe(true);
    const core = getVisualReviewCore();
    expect(core.presetName).toBe('today.populated');
    expect(core.theme).toBe('light');
  });
});
