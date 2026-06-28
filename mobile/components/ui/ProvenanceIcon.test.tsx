import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { ThemeProvider } from '@/theme';
import { ProvenanceIcon, provenancePresentation } from '@/components/ui';
import type { ProvenanceSource } from '@/components/ui';

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

// ---------------------------------------------------------------------------
// Expected provenance data
// ---------------------------------------------------------------------------

const PROVENANCE_CASES: Array<{
  source: ProvenanceSource;
  accessibilityLabel: string;
}> = [
  { source: 'nl_search', accessibilityLabel: 'Source: database search' },
  { source: 'barcode', accessibilityLabel: 'Source: barcode scan' },
  { source: 'label_scan', accessibilityLabel: 'Source: nutrition label capture' },
  { source: 'edited', accessibilityLabel: 'Source: edited by you' },
  { source: 'saved_food', accessibilityLabel: 'Source: saved food' },
  { source: 'rough_estimate', accessibilityLabel: 'Source: rough estimate' },
  { source: 'offline_pending', accessibilityLabel: 'Source: offline — pending sync' },
];

function mount(element: React.ReactElement) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(ThemeProvider, { override: 'light' }, element),
    );
  });
  return tree!;
}

// ---------------------------------------------------------------------------
// ProvenanceIcon component tests
// ---------------------------------------------------------------------------

describe('ProvenanceIcon', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  describe.each(PROVENANCE_CASES)('source: $source', ({ source, accessibilityLabel }) => {
    it(`renders with accessibilityLabel="${accessibilityLabel}"`, () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, { source }),
      );
      const node = tree.root.find(
        (n) => n.props.accessibilityLabel === accessibilityLabel,
      );
      expect(node).toBeTruthy();
    });

    it('has accessibilityRole="image"', () => {
      const tree = mount(
        React.createElement(ProvenanceIcon, { source }),
      );
      const node = tree.root.find(
        (n) => n.props.accessibilityRole === 'image',
      );
      expect(node).toBeTruthy();
    });
  });
});

// ---------------------------------------------------------------------------
// provenancePresentation() unit tests
// ---------------------------------------------------------------------------

describe('provenancePresentation()', () => {
  it.each(PROVENANCE_CASES)(
    'returns correct accessibilityLabel for "$source"',
    ({ source, accessibilityLabel }) => {
      const result = provenancePresentation(source);
      expect(result.accessibilityLabel).toBe(accessibilityLabel);
    },
  );

  it('returns a non-empty glyph for every source', () => {
    for (const { source } of PROVENANCE_CASES) {
      const result = provenancePresentation(source);
      expect(result.glyph.length).toBeGreaterThan(0);
    }
  });
});
