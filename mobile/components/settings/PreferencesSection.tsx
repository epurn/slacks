/**
 * The PREFERENCES section (FTY-203, extracted from SettingsScreen).
 *
 * Units, appearance (Light/Dark/System), and the weigh-in reminder cadence. The
 * cadence copy stays honest to the "encourage the trend, not the scale"
 * principle: low-frequency, fires only when a reading is due — never daily.
 */

import { StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale, type ColorSchemeOverride } from '@/theme';
import type { UnitsPreference } from '@/state/profile';
import {
  CADENCE_OPTIONS,
  type WeighInCadence,
} from '@/state/reminderScheduler';
import { SegmentedControl } from '@/components/ui';

import {
  GroupedCard,
  SectionHeader,
  Separator,
  type SettingsColors,
} from './primitives';
import { APPEARANCE_OPTIONS } from './copy';
import type { SettingsController } from './useSettingsController';

export function PreferencesSection({
  c,
  colors,
}: {
  c: SettingsController;
  colors: SettingsColors;
}) {
  return (
    <>
      <SectionHeader title="PREFERENCES" colors={colors} />
      <GroupedCard colors={colors}>
        <View style={styles.prefRow}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>Units</Text>
          <SegmentedControl<UnitsPreference>
            testID="units-segmented-control"
            options={[
              { value: 'metric', label: 'Metric' },
              { value: 'imperial', label: 'Imperial' },
            ]}
            selected={c.profile?.units_preference ?? 'metric'}
            onSelect={(v) => void c.handleUnitsChange(v)}
            accessibilityLabel="Units preference"
            style={styles.prefControl}
          />
        </View>
        <Separator colors={colors} />
        <View style={styles.prefRow}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>Appearance</Text>
          <SegmentedControl<ColorSchemeOverride>
            testID="appearance-segmented-control"
            options={APPEARANCE_OPTIONS}
            selected={c.appearance}
            onSelect={(v) => void c.handleAppearanceChange(v)}
            accessibilityLabel="Appearance"
            style={styles.prefControl}
          />
        </View>
        <Separator colors={colors} />
        <View style={styles.prefColumn}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>
            Weigh-in reminder
          </Text>
          <Text style={[styles.prefSubtitle, { color: colors.textMuted }]}>
            Low-frequency · fires when a reading is due
          </Text>
          <SegmentedControl<WeighInCadence>
            testID="cadence-segmented-control"
            options={CADENCE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            selected={c.cadence}
            onSelect={(v) => void c.handleCadenceChange(v)}
            accessibilityLabel="Weigh-in cadence"
          />
        </View>
      </GroupedCard>
    </>
  );
}

const styles = StyleSheet.create({
  prefRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    minHeight: 44,
  },
  prefColumn: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  prefLabel: {
    fontSize: typeScale.body,
  },
  // The inline control takes the remaining row width so its native segments
  // size evenly beside the label.
  prefControl: {
    flex: 1,
    maxWidth: 220,
    marginLeft: spacing.base,
    alignSelf: 'center',
  },
  prefSubtitle: {
    fontSize: typeScale.footnote,
  },
});
