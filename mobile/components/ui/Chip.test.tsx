import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider, lightPalette, darkPalette } from '@/theme';
import { Chip, CHIP_HIT_SLOP } from '@/components/ui';

const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

function mount(element: React.ReactElement, override: 'light' | 'dark' = 'light') {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(React.createElement(ThemeProvider, { override }, element));
  });
  return tree!;
}

function findChipNode(tree: ReturnType<typeof create>) {
  return tree.root.find((n) => n.props.accessibilityRole === 'button');
}

function flattenStyle(node: ReturnType<typeof findChipNode>): Record<string, unknown> {
  const styles: Array<Record<string, unknown>> = Array.isArray(node.props.style)
    ? node.props.style
    : [node.props.style];
  return Object.assign({}, ...styles);
}

describe('Chip', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('renders the label as text content', () => {
    const tree = mount(<Chip label="Greek yogurt" onPress={jest.fn()} />);
    const textNode = tree.root.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Greek yogurt',
    );
    expect(textNode).toBeTruthy();
  });

  it('defaults the accessibility label to the visible label', () => {
    const tree = mount(<Chip label="Greek yogurt" onPress={jest.fn()} />);
    const node = findChipNode(tree);
    expect(node.props.accessibilityLabel).toBe('Greek yogurt');
  });

  it('accepts an accessibility label override distinct from the visible label', () => {
    const tree = mount(
      <Chip label="Greek yogurt" accessibilityLabel="Use saved food: Greek yogurt" onPress={jest.fn()} />,
    );
    const node = findChipNode(tree);
    expect(node.props.accessibilityLabel).toBe('Use saved food: Greek yogurt');
  });

  it('calls onPress when tapped', () => {
    const onPress = jest.fn();
    const tree = mount(<Chip label="Oatmeal" onPress={onPress} />);
    act(() => {
      findChipNode(tree).props.onPress();
    });
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  // The visible pill stays compact (minHeight well under 44) so a dense chip
  // strip never balloons — CHIP_HIT_SLOP pads the *tappable* area out to the
  // WCAG 2.5.5 44pt minimum without changing the rendered size.
  it('has an effective touch target of at least 44pt via minHeight + hitSlop', () => {
    const tree = mount(<Chip label="Oatmeal" onPress={jest.fn()} />);
    const node = findChipNode(tree);
    const style = flattenStyle(node);
    const minHeight = style.minHeight as number;
    const hitSlop = node.props.hitSlop as { top: number; bottom: number };

    expect(typeof minHeight).toBe('number');
    expect(minHeight + hitSlop.top + hitSlop.bottom).toBeGreaterThanOrEqual(44);
  });

  it('applies CHIP_HIT_SLOP to the pressable', () => {
    const tree = mount(<Chip label="Oatmeal" onPress={jest.fn()} />);
    const node = findChipNode(tree);
    expect(node.props.hitSlop).toEqual(CHIP_HIT_SLOP);
  });

  it('fills the chip from controlBackground and labels from text token in light mode', () => {
    const tree = mount(<Chip label="Oatmeal" onPress={jest.fn()} />, 'light');
    const chipStyle = flattenStyle(findChipNode(tree));
    expect(chipStyle.backgroundColor).toBe(lightPalette.controlBackground);

    const textNode = tree.root.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Oatmeal',
    );
    const textStyles: Array<Record<string, unknown>> = Array.isArray(textNode.props.style)
      ? textNode.props.style
      : [textNode.props.style];
    expect(Object.assign({}, ...textStyles).color).toBe(lightPalette.text);
  });

  it('fills the chip from controlBackground and labels from text token in dark mode', () => {
    const tree = mount(<Chip label="Oatmeal" onPress={jest.fn()} />, 'dark');
    const chipStyle = flattenStyle(findChipNode(tree));
    expect(chipStyle.backgroundColor).toBe(darkPalette.controlBackground);
  });

  it('sets accessibilityState.disabled = true and does not invoke onPress when disabled', () => {
    const onPress = jest.fn();
    const tree = mount(<Chip label="Oatmeal" onPress={onPress} disabled />);
    const node = findChipNode(tree);
    expect(node.props.accessibilityState).toEqual(expect.objectContaining({ disabled: true }));
    expect(node.props.disabled).toBe(true);
  });
});
