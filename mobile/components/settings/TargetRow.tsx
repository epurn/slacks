/**
 * A calorie or macro target row (FTY-203, extracted from SettingsScreen).
 *
 * Shows: effective value + unit, a provenance line ("└ from your goal + metrics"
 * or "✎ set by you"), and a Reset button when the target is overridden. The
 * provenance marker carries a VoiceOver label as required by the accessibility
 * spec ("Every number shows where it came from").
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale, radius } from '@/theme';
import type { TargetReadModel } from '@/api/dailySummary';

import type { SettingsColors } from './primitives';

export function TargetRow({
  label,
  unit,
  component,
  onOverride,
  onReset,
  colors,
  testID,
}: {
  label: string;
  unit: string;
  component: TargetReadModel['calories'];
  onOverride: () => void;
  onReset: () => void;
  colors: SettingsColors;
  testID?: string;
}) {
  const isUser = component.source === 'user';
  const provenanceLabel = isUser
    ? 'Set by you — tap Reset to restore the derived value'
    : 'Derived from your goal and metrics';

  return (
    <View style={styles.targetRow} testID={testID}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}: ${component.effective} ${unit}. ${provenanceLabel}`}
        accessibilityHint="Double-tap to set a custom value"
        onPress={onOverride}
        style={styles.targetRowMain}
      >
        <Text style={[styles.targetLabel, { color: colors.text }]}>{label}</Text>
        <View>
          <Text style={[styles.targetValue, { color: colors.text }]}>
            {`${component.effective} ${unit}`}
          </Text>
          <Text
            style={[
              styles.targetProvenance,
              { color: isUser ? colors.accentText : colors.textMuted },
            ]}
            accessibilityLabel={provenanceLabel}
            accessibilityRole="text"
          >
            {isUser ? '✎ set by you' : '└ from your goal + metrics'}
          </Text>
        </View>
      </Pressable>
      {isUser && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Reset ${label} to derived value of ${component.derived} ${unit}`}
          onPress={onReset}
          style={[styles.resetButton, { borderColor: colors.separator }]}
        >
          <Text style={[styles.resetLabel, { color: colors.textSecondary }]}>Reset</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  targetRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 64,
    gap: spacing.sm,
  },
  targetRowMain: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 44,
  },
  targetLabel: {
    fontSize: typeScale.body,
  },
  targetValue: {
    fontSize: typeScale.body,
    fontWeight: '600',
    textAlign: 'right',
  },
  targetProvenance: {
    fontSize: typeScale.caption1,
    textAlign: 'right',
    marginTop: 2,
  },
  resetButton: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    minHeight: 30,
    minWidth: 56,
    alignItems: 'center',
    justifyContent: 'center',
  },
  resetLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '500',
  },
});
