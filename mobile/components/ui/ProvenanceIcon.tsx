import { StyleSheet, View } from 'react-native';

import type { ItemSourceDTO } from '@/api/derivedItems';
import { useTheme } from '@/theme';

import { AppIcon, type AppIconName } from './AppIcon';

/**
 * SF Symbol + VoiceOver label for a value's provenance, so screen-reader
 * users receive the same source signal as sighted users.
 */
export interface ProvenancePresentation {
  readonly icon: AppIconName;
  readonly accessibilityLabel: string;
}

/**
 * Resolves the provenance presentation for a server item source descriptor
 * (FTY-092 `ItemSourceDTO`, the evidence-hierarchy `source_type`). A direct
 * user edit (`is_edited`) is treated as just another provenance and takes
 * precedence over the underlying source type per the UX spec; a missing source
 * falls back to an "unknown" icon rather than crashing.
 */
export function provenancePresentation(
  source: ItemSourceDTO | null | undefined,
  is_edited = false,
): ProvenancePresentation {
  if (is_edited) {
    return { icon: 'pencil', accessibilityLabel: 'Edited by you' };
  }
  if (!source) {
    return { icon: 'questionmark.circle', accessibilityLabel: 'Source unknown' };
  }
  switch (source.source_type) {
    case 'trusted_nutrition_database':
      return { icon: 'magnifyingglass', accessibilityLabel: `Source: ${source.label}` };
    case 'product_database':
      return { icon: 'barcode', accessibilityLabel: `Source: ${source.label}` };
    case 'user_label':
      return { icon: 'camera', accessibilityLabel: `Source: ${source.label}` };
    case 'official_source':
      return { icon: 'globe', accessibilityLabel: `Source: ${source.label}` };
    case 'reference_source':
      return { icon: 'book.closed', accessibilityLabel: `Source: ${source.label}` };
    case 'model_prior':
      return { icon: 'plus.forwardslash.minus', accessibilityLabel: 'Rough estimate' };
  }
}

/**
 * The single, always-on provenance icon for a food item's nutritional data,
 * keyed off the real server `ItemSourceDTO` (FTY-092). Shows a small SF Symbol
 * for the source type with a built-in VoiceOver label. Quiet by default — icon
 * only; the full evidence is one tap away (handled by the parent sheet or item
 * row). When `is_edited` is true it renders the edited icon regardless of the
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
  const { icon, accessibilityLabel } = provenancePresentation(source, is_edited);

  return (
    <View style={styles.icon}>
      <AppIcon
        name={icon}
        size={16}
        color={colors.textMuted}
        accessibilityLabel={accessibilityLabel}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  icon: {
    width: 22,
    alignItems: 'center',
  },
});
