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
import {
  SegmentedControl,
  MenuPicker,
  type MenuPickerOption,
} from '@/components/ui';

import {
  GroupedCard,
  SectionHeader,
  Separator,
  type SettingsColors,
} from './primitives';
import { APPEARANCE_OPTIONS } from './copy';
import type { SettingsController } from './useSettingsController';

// The cadence menu shows label + value only; `days` is the scheduler's concern.
const CADENCE_MENU_OPTIONS: readonly MenuPickerOption<WeighInCadence>[] =
  CADENCE_OPTIONS.map((o) => ({ value: o.value, label: o.label }));

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
          <View style={styles.prefControl}>
            <SegmentedControl<UnitsPreference>
              testID="units-segmented-control"
              options={[
                { value: 'metric', label: 'Metric' },
                { value: 'imperial', label: 'Imperial' },
              ]}
              selected={c.profile?.units_preference ?? 'metric'}
              onSelect={(v) => void c.handleUnitsChange(v)}
              accessibilityLabel="Units preference"
            />
          </View>
        </View>
        <Separator colors={colors} />
        <View style={styles.prefRow}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>Appearance</Text>
          <View style={styles.prefControl}>
            <SegmentedControl<ColorSchemeOverride>
              testID="appearance-segmented-control"
              options={APPEARANCE_OPTIONS}
              selected={c.appearance}
              onSelect={(v) => void c.handleAppearanceChange(v)}
              accessibilityLabel="Appearance"
            />
          </View>
        </View>
        <Separator colors={colors} />
        {/*
          Cadence grew to seven options (FTY-403), too many for the equal-width
          segmented control — so it's a native menu/picker: the row shows the
          current cadence and taps to reveal the full, untruncated list.
        */}
        <View style={styles.prefRow}>
          <View style={styles.prefLabelBlock}>
            <Text style={[styles.prefLabel, { color: colors.text }]}>
              Weigh-in reminder
            </Text>
            <Text style={[styles.prefSubtitle, { color: colors.textMuted }]}>
              Fires once when a reading is due
            </Text>
          </View>
          <MenuPicker<WeighInCadence>
            testID="cadence-menu-picker"
            title="Weigh-in reminder"
            options={CADENCE_MENU_OPTIONS}
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
  // The cadence row's leading label + subtitle stack; the MenuPicker trigger
  // sits to their right (flexes to leave the label block the remaining width).
  prefLabelBlock: {
    flex: 1,
    gap: spacing.xs,
  },
  prefLabel: {
    fontSize: typeScale.body,
  },
  // Wraps the inline control so this View (a direct row child) claims the
  // remaining row width via flex; the SegmentedControl then stretches to fill
  // it. The flex must live on a direct child of the row — SegmentedControl nests
  // its native control inside a caption wrapper (FTY-222), so a `style` passed
  // straight to it lands in that column wrapper and never sizes the row.
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
