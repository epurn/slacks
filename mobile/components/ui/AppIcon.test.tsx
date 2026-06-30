import React from 'react';
import { act, create } from 'react-test-renderer';
import { AppIcon } from './AppIcon';

// expo-symbols is a native module — replace with a View stub that exposes the
// symbol name via testID so tests can assert which glyph was requested.
jest.mock('expo-symbols', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require('react');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require('react-native');
  return {
    SymbolView: ({
      name,
      tintColor,
      accessibilityLabel,
    }: {
      name: string;
      tintColor?: string;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

describe('AppIcon', () => {
  it('renders the SymbolView for the given SF Symbol name', () => {
    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(<AppIcon name="gear" />);
    });
    const node = tree!.root.find((n) => n.props.testID === 'sf-symbol-gear');
    expect(node).toBeTruthy();
  });

  it('passes accessibilityLabel to SymbolView', () => {
    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(<AppIcon name="gear" accessibilityLabel="Open settings" />);
    });
    const node = tree!.root.find((n) => n.props.accessibilityLabel === 'Open settings');
    expect(node).toBeTruthy();
  });

  it('renders the four chrome SF Symbols without error', () => {
    const names = [
      'sun.max',
      'plus',
      'chart.line.uptrend.xyaxis',
      'gear',
    ] as const;

    for (const name of names) {
      let tree: ReturnType<typeof create>;
      act(() => {
        tree = create(<AppIcon name={name} />);
      });
      const node = tree!.root.find((n) => n.props.testID === `sf-symbol-${name}`);
      expect(node).toBeTruthy();
    }
  });
});
