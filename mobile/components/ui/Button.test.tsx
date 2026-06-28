import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider, lightPalette, darkPalette } from '@/theme';
import { Button } from '@/components/ui';

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

function mount(
  element: React.ReactElement,
  override: 'light' | 'dark' = 'light',
) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(ThemeProvider, { override }, element),
    );
  });
  return tree!;
}

/** Flattened color of the Button's label Text node. */
function labelColor(tree: ReturnType<typeof create>, label: string): unknown {
  const textNode = tree.root.find(
    (n) => (n.type as unknown as string) === 'Text' && n.props.children === label,
  );
  const styles: Array<Record<string, unknown>> = Array.isArray(textNode.props.style)
    ? textNode.props.style
    : [textNode.props.style];
  return Object.assign({}, ...styles).color;
}

describe('Button', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('renders with the provided label as text content', () => {
    const tree = mount(React.createElement(Button, { label: 'Save' }));
    const textNode = tree.root.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Save',
    );
    expect(textNode).toBeTruthy();
  });

  it('has accessibilityRole="button"', () => {
    const tree = mount(React.createElement(Button, { label: 'Continue' }));
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'button',
    );
    expect(node).toBeTruthy();
  });

  it('has minHeight >= 44 in its style (tap target requirement)', () => {
    const tree = mount(React.createElement(Button, { label: 'Tap me' }));
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'button',
    );
    const styles: Array<Record<string, unknown>> = Array.isArray(node.props.style)
      ? node.props.style
      : [node.props.style];
    const combined = Object.assign({}, ...styles);
    expect(typeof combined.minHeight).toBe('number');
    expect(combined.minHeight as number).toBeGreaterThanOrEqual(44);
  });

  it('sets accessibilityState.disabled = true when disabled prop is true', () => {
    const tree = mount(
      React.createElement(Button, { label: 'Submit', disabled: true }),
    );
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'button',
    );
    expect(node.props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: true }),
    );
  });

  it('disabled button has disabled prop set (does not invoke onPress)', () => {
    const onPress = jest.fn();
    const tree = mount(
      React.createElement(Button, { label: 'Submit', disabled: true, onPress }),
    );
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'button',
    );
    // Pressable receives disabled=true — the native layer won't fire onPress
    expect(node.props.disabled).toBe(true);
    // onPress has not been called
    expect(onPress).not.toHaveBeenCalled();
  });

  it('primary label uses accentForeground (readable on accent) in light mode', () => {
    const tree = mount(
      React.createElement(Button, { label: 'Save', variant: 'primary' }),
      'light',
    );
    expect(labelColor(tree, 'Save')).toBe(lightPalette.accentForeground);
  });

  it('primary label uses accentForeground (readable on accent) in dark mode', () => {
    // Regression guard: the primary label must NOT be near-white `text`, which
    // would be unreadable on the light dark-mode amber accent.
    const tree = mount(
      React.createElement(Button, { label: 'Save', variant: 'primary' }),
      'dark',
    );
    expect(labelColor(tree, 'Save')).toBe(darkPalette.accentForeground);
    expect(labelColor(tree, 'Save')).not.toBe(darkPalette.text);
  });

  it('calls onPress when enabled', () => {
    const onPress = jest.fn();
    const tree = mount(
      React.createElement(Button, { label: 'Submit', onPress }),
    );
    const node = tree.root.find(
      (n) => n.props.accessibilityRole === 'button',
    );
    act(() => {
      node.props.onPress();
    });
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});
