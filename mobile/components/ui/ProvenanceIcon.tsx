import { Text, StyleSheet } from 'react-native';

import type { ItemSourceDTO } from '@/api/derivedItems';
import { useTheme } from '@/theme';

/**
 * Compact glyph + VoiceOver label for a value's provenance, so screen-reader
 * users receive the same source signal as sighted users.
 */
export interface ProvenancePresentation {
  readonly glyph: string;
  readonly accessibilityLabel: string;
}

/**
 * Resolves the provenance presentation for a server item source descriptor
 * (FTY-092 `ItemSourceDTO`, the evidence-hierarchy `source_type`). A direct
 * user edit (`is_edited`) is treated as just another provenance and takes
 * precedence over the underlying source type per the UX spec; a missing source
 * falls back to an "unknown" glyph rather than crashing.
 */
export function provenancePresentation(
  source: ItemSourceDTO | null | undefined,
  is_edited = false,
): ProvenancePresentation {
  if (is_edited) {
    return { glyph: '✎', accessibilityLabel: 'Edited by you' };
  }
  if (!source) {
    return { glyph: '·', accessibilityLabel: 'Source unknown' };
  }
  switch (source.source_type) {
    case 'trusted_nutrition_database':
      return { glyph: '🔍', accessibilityLabel: `Source: ${source.label}` };
    case 'product_database':
      return { glyph: '📊', accessibilityLabel: `Source: ${source.label}` };
    case 'user_label':
      return { glyph: '📷', accessibilityLabel: `Source: ${source.label}` };
    case 'official_source':
      return { glyph: '🌐', accessibilityLabel: `Source: ${source.label}` };
    case 'reference_source':
      return { glyph: '📖', accessibilityLabel: `Source: ${source.label}` };
    case 'model_prior':
      return { glyph: '≈', accessibilityLabel: 'Rough estimate' };
  }
}

/**
 * The single, always-on provenance icon for a food item's nutritional data,
 * keyed off the real server `ItemSourceDTO` (FTY-092). Shows a small glyph for
 * the source type with a built-in VoiceOver label. Quiet by default — icon
 * only; the full evidence is one tap away (handled by the parent sheet or item
 * row). When `is_edited` is true it renders the edited glyph regardless of the
 * underlying source type.
 */
export function ProvenanceIcon({
  source,
  is_edited = false,
}: {
  source?: ItemSourceDTO | null;
  is_edited?: boolean;
}) {
  const { colors } = useTheme();
  const { glyph, accessibilityLabel } = provenancePresentation(source, is_edited);

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
