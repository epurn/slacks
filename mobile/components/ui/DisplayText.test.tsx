import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider, typeScale, DISPLAY_FONT_FAMILY, displayTracking } from '@/theme';
import { DisplayText } from '@/components/ui';

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

function mount(element: React.ReactElement) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(React.createElement(ThemeProvider, { override: 'light' }, element));
  });
  return tree!;
}

function flattenedStyle(style: unknown): Record<string, unknown> {
  const styles: Array<Record<string, unknown>> = Array.isArray(style) ? style : [style];
  return Object.assign({}, ...styles);
}

describe('DisplayText', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('renders its children', () => {
    const tree = mount(React.createElement(DisplayText, null, 'Today'));
    const textNode = tree.root.findAll(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Today',
    );
    expect(textNode.length).toBeGreaterThan(0);
  });

  it('applies DISPLAY_FONT_FAMILY', () => {
    const tree = mount(React.createElement(DisplayText, null, 'Today'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).fontFamily).toBe(DISPLAY_FONT_FAMILY);
  });

  it('applies displayTracking as letterSpacing', () => {
    const tree = mount(React.createElement(DisplayText, null, 'Today'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).letterSpacing).toBe(displayTracking);
  });

  it('defaults to typeScale.largeTitle', () => {
    const tree = mount(React.createElement(DisplayText, null, 'Today'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).fontSize).toBe(typeScale.largeTitle);
  });

  it('uses fontSize from typeScale.title2 when scale="title2"', () => {
    const tree = mount(React.createElement(DisplayText, { scale: 'title2' }, 'Today'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).fontSize).toBe(typeScale.title2);
  });

  it('does not set fontVariant by default', () => {
    const tree = mount(React.createElement(DisplayText, null, 'Today'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).fontVariant).toBeUndefined();
  });

  it('applies fontVariant: ["tabular-nums"] when tabularNums is set', () => {
    const tree = mount(React.createElement(DisplayText, { tabularNums: true }, '42'));
    const textNode = tree.root.find((n) => (n.type as unknown as string) === 'Text');
    expect(flattenedStyle(textNode.props.style).fontVariant).toEqual(['tabular-nums']);
  });

  it('renders correctly wrapped in ThemeProvider without throwing', () => {
    expect(() => {
      mount(React.createElement(DisplayText, null, 'Today'));
    }).not.toThrow();
  });
});
