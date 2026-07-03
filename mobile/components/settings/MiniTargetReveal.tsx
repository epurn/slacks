/**
 * Mini target-reveal (FTY-203, extracted from SettingsScreen).
 *
 * After a goal or body-metric edit recomputes the plan, the new calorie + macro
 * targets fade in place (skeleton → fade, no navigation) so the user sees their
 * action registered where they are — the "calm, in place" acknowledgement. A
 * clamped calorie value is marked with an asterisk that ties to the safe-limit
 * note; the whole card carries a single VoiceOver summary of the new targets.
 */

import { Animated, StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale, radius } from '@/theme';
import type { TargetReadModel } from '@/api/dailySummary';

import type { SettingsColors } from './primitives';

export function MiniTargetReveal({
  target,
  clamped,
  opacity,
  colors,
}: {
  target: TargetReadModel;
  clamped: boolean;
  opacity: Animated.Value;
  colors: SettingsColors;
}) {
  return (
    <Animated.View
      style={[
        styles.revealCard,
        {
          backgroundColor: colors.surfaceRaised,
          borderRadius: radius.lg,
          opacity,
        },
      ]}
      accessibilityLabel={`Updated targets: ${target.calories.effective} kcal calories, ${target.protein_g.effective} g protein, ${target.carbs_g.effective} g carbs, ${target.fat_g.effective} g fat${clamped ? '. Adjusted to a safe limit' : ''}`}
      testID="mini-target-reveal"
    >
      <Text style={[styles.revealTitle, { color: colors.textSecondary }]}>
        Updated targets
      </Text>
      <View style={styles.revealRow}>
        <RevealItem
          label="Cal"
          value={target.calories.effective}
          unit="kcal"
          clamped={clamped}
          colors={colors}
        />
        <RevealItem
          label="P"
          value={target.protein_g.effective}
          unit="g"
          clamped={false}
          colors={colors}
        />
        <RevealItem
          label="C"
          value={target.carbs_g.effective}
          unit="g"
          clamped={false}
          colors={colors}
        />
        <RevealItem
          label="F"
          value={target.fat_g.effective}
          unit="g"
          clamped={false}
          colors={colors}
        />
      </View>
      {clamped && (
        <Text
          style={[styles.revealClampNote, { color: colors.textMuted }]}
          testID="reveal-clamp-note"
        >
          * Adjusted to a safe limit
        </Text>
      )}
    </Animated.View>
  );
}

function RevealItem({
  label,
  value,
  unit,
  clamped,
  colors,
}: {
  label: string;
  value: number;
  unit: string;
  clamped: boolean;
  colors: SettingsColors;
}) {
  // A clamped value is the safety boundary, not the requested plan — mark it with
  // an asterisk that ties to the "Adjusted to a safe limit" note below the row.
  return (
    <View style={styles.revealItem}>
      <Text style={[styles.revealValue, { color: colors.text }]}>
        {`${value}${clamped ? '*' : ''}`}
      </Text>
      <Text style={[styles.revealUnit, { color: colors.textMuted }]}>
        {`${unit} ${label}`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  revealCard: {
    padding: spacing.md,
    marginTop: spacing.xs,
    marginBottom: spacing.xs,
  },
  revealTitle: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
  },
  revealRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  revealItem: {
    alignItems: 'center',
  },
  revealValue: {
    fontSize: typeScale.headline,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  revealUnit: {
    fontSize: typeScale.caption1,
    marginTop: 2,
  },
  revealClampNote: {
    fontSize: typeScale.caption1,
    marginTop: spacing.sm,
  },
});
