import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider, typeScale } from '@/theme';
import { ThemedNumber } from '@/components/ui';

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

describe('ThemedNumber', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('renders its value as a string child', () => {
    const tree = mount(React.createElement(ThemedNumber, { value: 42 }));
    const textNode = tree.root.findAll(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === '42',
    );
    expect(textNode.length).toBeGreaterThan(0);
  });

  it('renders a string value as a string child', () => {
    const tree = mount(React.createElement(ThemedNumber, { value: '3.14' }));
    const textNode = tree.root.findAll(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === '3.14',
    );
    expect(textNode.length).toBeGreaterThan(0);
  });

  it('has fontVariant: ["tabular-nums"] in its style', () => {
    const tree = mount(React.createElement(ThemedNumber, { value: 100 }));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    // style is an array — flatten to find the object containing fontVariant
    const styles: Array<Record<string, unknown>> = Array.isArray(textNode.props.style)
      ? textNode.props.style
      : [textNode.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.fontVariant).toEqual(['tabular-nums']);
  });

  it('uses fontSize from typeScale.heroDisplay by default', () => {
    const tree = mount(React.createElement(ThemedNumber, { value: 0 }));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    const styles: Array<Record<string, unknown>> = Array.isArray(textNode.props.style)
      ? textNode.props.style
      : [textNode.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.fontSize).toBe(typeScale.heroDisplay);
  });

  it('uses fontSize from typeScale.title1 when scale="title1"', () => {
    const tree = mount(
      React.createElement(ThemedNumber, { value: 99, scale: 'title1' }),
    );
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    const styles: Array<Record<string, unknown>> = Array.isArray(textNode.props.style)
      ? textNode.props.style
      : [textNode.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.fontSize).toBe(typeScale.title1); // 28
  });

  it('renders correctly wrapped in ThemeProvider without throwing', () => {
    expect(() => {
      mount(React.createElement(ThemedNumber, { value: 1234 }));
    }).not.toThrow();
  });
});
