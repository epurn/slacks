/**
 * Shared visual-review settled-marker helper tests (FTY-270).
 *
 * Proves the contract a modal-based seam (FTY-262..268) relies on:
 *   - it emits the canonical `visual-review-settled:<preset>` testID once
 *     `preset` has been stable and network-quiet for QUIET_MS,
 *   - a new mock request restarts the quiet window (reused, not forked, from
 *     FTY-247),
 *   - the optional `ready` gate defers the marker for a sub-state with its own
 *     async readiness signal,
 *   - it is inert whenever `preset` is null/undefined, and inert outside E2E
 *     mode even when a preset name is supplied.
 */

import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';

import { registerVisualReviewPreset, __resetVisualReviewRegistry } from './registry';
import {
  activateVisualReviewPreset,
  recordVisualReviewServed,
  __deactivateVisualReview,
} from './session';
import { QUIET_MS, VisualReviewSettleMarker } from './VisualReviewSettleMarker';

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

function enterE2EMode(): void {
  gThis['__DEV__'] = true;
  process.env['EXPO_PUBLIC_SLACKS_E2E'] = 'true';
}

let mounted: ReactTestRenderer | null = null;

function mount(
  preset: string | null | undefined,
  ready?: boolean,
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<VisualReviewSettleMarker preset={preset} ready={ready} />);
  });
  mounted = tree;
  return tree;
}

beforeEach(() => {
  jest.useFakeTimers();
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
    delete process.env['EXPO_PUBLIC_SLACKS_E2E'];
  } else {
    process.env['EXPO_PUBLIC_SLACKS_E2E'] = ORIGINAL_E2E_ENV;
  }
});

function hasMarker(tree: ReactTestRenderer, testID: string): boolean {
  return tree.root.findAll((n) => n.props.testID === testID).length > 0;
}

describe('VisualReviewSettleMarker', () => {
  it('emits the canonical testID for the given preset once settled', () => {
    enterE2EMode();
    const tree = mount('correction.typeahead');

    // Not yet: the network-quiet window has not elapsed.
    expect(hasMarker(tree, 'visual-review-settled:correction.typeahead')).toBe(
      false,
    );

    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 10);
    });
    expect(hasMarker(tree, 'visual-review-settled:correction.typeahead')).toBe(
      true,
    );
  });

  it('restarts the quiet window when a new mock request arrives', () => {
    enterE2EMode();
    // recordVisualReviewServed only bumps the fetch tick while a preset is
    // active in the shared session — register + activate one under the same
    // name this marker renders for.
    registerVisualReviewPreset({
      name: 'weight.log_sheet',
      route: '/',
      settledPath: '/',
    });
    activateVisualReviewPreset('weight.log_sheet', null);
    const tree = mount('weight.log_sheet');

    act(() => {
      jest.advanceTimersByTime(QUIET_MS - 20);
      recordVisualReviewServed();
    });
    act(() => {
      jest.advanceTimersByTime(30);
    });
    expect(hasMarker(tree, 'visual-review-settled:weight.log_sheet')).toBe(
      false,
    );
    act(() => {
      jest.advanceTimersByTime(QUIET_MS);
    });
    expect(hasMarker(tree, 'visual-review-settled:weight.log_sheet')).toBe(
      true,
    );
  });

  it('defers to the optional ready gate for a sub-state with its own async signal', () => {
    enterE2EMode();
    const tree = mount('correction.typeahead', false);

    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 10);
    });
    // Network-quiet window elapsed, but the caller's readiness signal is false.
    expect(hasMarker(tree, 'visual-review-settled:correction.typeahead')).toBe(
      false,
    );

    act(() => {
      tree.update(
        <VisualReviewSettleMarker preset="correction.typeahead" ready />,
      );
    });
    expect(hasMarker(tree, 'visual-review-settled:correction.typeahead')).toBe(
      true,
    );
  });

  it('is inert when preset is null (this seam is not the active one)', () => {
    enterE2EMode();
    const tree = mount(null);

    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 50);
    });
    expect(
      tree.root.findAll((n) => typeof n.props.testID === 'string').length,
    ).toBe(0);
  });

  it('is inert outside E2E mode even with a preset supplied', () => {
    gThis['__DEV__'] = false;
    const tree = mount('correction.detail');

    act(() => {
      jest.advanceTimersByTime(QUIET_MS + 50);
    });
    expect(
      hasMarker(tree, 'visual-review-settled:correction.detail'),
    ).toBe(false);
  });
});
