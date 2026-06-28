import { Text, StyleSheet } from 'react-native';
import { useTheme } from '@/theme';

/**
 * The set of source / provenance types for a food item's nutritional data.
 * Each key maps to a compact glyph and a VoiceOver label so screen-reader
 * users receive the same provenance signal as sighted users.
 */
export type ProvenanceSource =
  | 'nl_search'       // Natural-language / USDA database search
  | 'barcode'         // Barcode scan
  | 'label_scan'      // Nutrition label OCR capture
  | 'edited'          // User manually edited
  | 'saved_food'      // Saved food (typeahead selection)
  | 'rough_estimate'  // Rough estimate (low-confidence)
  | 'offline_pending'; // Captured offline; pending resolution

interface ProvenancePresentation {
  readonly glyph: string;
  readonly accessibilityLabel: string;
}

const PROVENANCE_MAP: Record<ProvenanceSource, ProvenancePresentation> = {
  nl_search: {
    glyph: '🔍',
    accessibilityLabel: 'Source: database search',
  },
  barcode: {
    glyph: '▦',
    accessibilityLabel: 'Source: barcode scan',
  },
  label_scan: {
    glyph: '📷',
    accessibilityLabel: 'Source: nutrition label capture',
  },
  edited: {
    glyph: '✎',
    accessibilityLabel: 'Source: edited by you',
  },
  saved_food: {
    glyph: '🔖',
    accessibilityLabel: 'Source: saved food',
  },
  rough_estimate: {
    glyph: '≈',
    accessibilityLabel: 'Source: rough estimate',
  },
  offline_pending: {
    glyph: '⏳',
    accessibilityLabel: 'Source: offline — pending sync',
  },
};

/** Returns the provenance presentation for a given source key. */
export function provenancePresentation(source: ProvenanceSource): ProvenancePresentation {
  return PROVENANCE_MAP[source];
}

/**
 * Compact provenance icon for a food item. Shows a small always-on glyph
 * indicating where the nutritional data came from, with a built-in VoiceOver
 * label. Quiet by default — icon only; detail is one tap away (handled by
 * the parent sheet or item row).
 */
export function ProvenanceIcon({ source }: { source: ProvenanceSource }) {
  const { colors } = useTheme();
  const { glyph, accessibilityLabel } = PROVENANCE_MAP[source];

  return (
    <Text
      style={[styles.icon, { color: colors.textMuted }]}
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
    >
      {glyph}
    </Text>
  );
}

const styles = StyleSheet.create({
  icon: {
    fontSize: 16,
    width: 22,
    textAlign: 'center',
  },
});
