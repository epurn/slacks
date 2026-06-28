import React from 'react';
import { act, create } from 'react-test-renderer';
import { AccessibilityInfo, useColorScheme } from 'react-native';
import { ThemeProvider } from '@/theme';
import { Skeleton } from '@/components/ui';

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

function mount(element: React.ReactElement) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(ThemeProvider, { override: 'light' }, element),
    );
  });
  return tree!;
}

describe('Skeleton', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
    // Default: Reduce Motion is off
    jest
      .spyOn(AccessibilityInfo, 'isReduceMotionEnabled')
      .mockResolvedValue(false);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders with accessibilityRole="progressbar"', () => {
    const tree = mount(React.createElement(Skeleton, null));
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'progressbar',
    );
    expect(node).toBeTruthy();
  });

  it('renders with accessibilityLabel="Loading"', () => {
    const tree = mount(React.createElement(Skeleton, null));
    const node = tree.root.find(
      (n) => n.props.accessibilityLabel === 'Loading',
    );
    expect(node).toBeTruthy();
  });

  it('applies the specified width to the container', () => {
    const tree = mount(React.createElement(Skeleton, { width: 120 }));
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'progressbar',
    );
    const styles: Array<Record<string, unknown>> = Array.isArray(node.props.style)
      ? node.props.style
      : [node.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.width).toBe(120);
  });

  it('applies the specified height to the container', () => {
    const tree = mount(React.createElement(Skeleton, { height: 48 }));
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'progressbar',
    );
    const styles: Array<Record<string, unknown>> = Array.isArray(node.props.style)
      ? node.props.style
      : [node.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.height).toBe(48);
  });

  it('does not crash when Reduce Motion is enabled', async () => {
    jest
      .spyOn(AccessibilityInfo, 'isReduceMotionEnabled')
      .mockResolvedValue(true);

    let tree: ReturnType<typeof create> | null = null;
    act(() => {
      tree = create(
        React.createElement(
          ThemeProvider,
          { override: 'light' },
          React.createElement(Skeleton, { width: 80, height: 20 }),
        ),
      );
    });
    // Let the isReduceMotionEnabled promise resolve inside useEffect
    await act(async () => {});
    expect(tree).not.toBeNull();
    expect(
      tree!.root.find((n) => n.props.accessibilityRole === 'progressbar'),
    ).toBeTruthy();
  });
});
