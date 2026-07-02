import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider } from '@/theme';
import { ProvenanceIcon, provenancePresentation } from '@/components/ui';
import type { ItemSourceDTO } from '@/api/derivedItems';

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SOURCE_LABELS: Record<ItemSourceDTO['source_type'], string> = {
  trusted_nutrition_database: 'USDA',
  product_database: 'Open Food Facts',
  official_source: 'example.com',
  user_label: 'Label scan',
  reference_source: 'reference.example.com',
  model_prior: 'Rough estimate',
};

function sourceOf(source_type: ItemSourceDTO['source_type']): ItemSourceDTO {
  return {
    source_type,
    label: SOURCE_LABELS[source_type],
    ref: `${source_type}:123`,
  };
}

function mount(element: React.ReactElement) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(ThemeProvider, { override: 'light' }, element),
    );
  });
  return tree!;
}

function firstA11yLabel(tree: ReturnType<typeof create>): string {
  return tree.root.find((n) => !!n.props.accessibilityLabel).props
    .accessibilityLabel as string;
}

// ---------------------------------------------------------------------------
// ProvenanceIcon component tests
// ---------------------------------------------------------------------------

describe('ProvenanceIcon', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  describe('source types', () => {
    it.each<[ItemSourceDTO['source_type'], string]>([
      ['trusted_nutrition_database', 'USDA'],
      ['product_database', 'Open Food Facts'],
      ['user_label', 'Label scan'],
      ['official_source', 'example.com'],
      ['reference_source', 'reference.example.com'],
    ])('%s: a11y label includes the source label', (sourceType, expectedLabel) => {
      const tree = mount(
        React.createElement(ProvenanceIcon, { source: sourceOf(sourceType) }),
      );
      expect(firstA11yLabel(tree)).toContain(expectedLabel);
    });

    it("model_prior: a11y label says 'Rough estimate'", () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, { source: sourceOf('model_prior') }),
      );
      expect(firstA11yLabel(tree)).toBe('Rough estimate');
    });

    it('null source: renders without crash with a truthy a11y label', () => {
      const tree = mount(React.createElement(ProvenanceIcon, { source: null }));
      expect(firstA11yLabel(tree)).toBeTruthy();
    });

    it('undefined source: renders without crash', () => {
      const tree = mount(React.createElement(ProvenanceIcon, {}));
      expect(firstA11yLabel(tree)).toBeTruthy();
    });
  });

  describe('is_edited flag', () => {
    it("is_edited overrides the source type with an 'Edited by you' label", () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, {
          source: sourceOf('trusted_nutrition_database'),
          is_edited: true,
        }),
      );
      expect(firstA11yLabel(tree)).toBe('Edited by you');
    });

    it('is_edited=false shows the normal source label', () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, {
          source: sourceOf('trusted_nutrition_database'),
          is_edited: false,
        }),
      );
      expect(firstA11yLabel(tree)).toContain('USDA');
    });

    it('is_edited with a null source still shows the edited label', () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, { source: null, is_edited: true }),
      );
      expect(firstA11yLabel(tree)).toBe('Edited by you');
    });
  });

  it('has accessibilityRole="image"', () => {
    const tree = mount(
      React.createElement(ProvenanceIcon, {
        source: sourceOf('product_database'),
      }),
    );
    const node = tree.root.find((n) => n.props.accessibilityRole === 'image');
    expect(node).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// provenancePresentation() unit tests
// ---------------------------------------------------------------------------

describe('provenancePresentation()', () => {
  it('returns a non-empty glyph for every source type, null, and edited', () => {
    const sourceTypes = Object.keys(SOURCE_LABELS) as ItemSourceDTO['source_type'][];
    for (const sourceType of sourceTypes) {
      expect(provenancePresentation(sourceOf(sourceType)).glyph.length).toBeGreaterThan(0);
    }
    expect(provenancePresentation(null).glyph.length).toBeGreaterThan(0);
    expect(provenancePresentation(sourceOf('user_label'), true).glyph.length).toBeGreaterThan(0);
  });

  it('is_edited takes precedence over the source type', () => {
    const result = provenancePresentation(sourceOf('trusted_nutrition_database'), true);
    expect(result.accessibilityLabel).toBe('Edited by you');
  });
});
