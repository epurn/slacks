/**
 * The DATA & ABOUT section (FTY-203, extracted from SettingsScreen).
 *
 * Honest "Coming soon" disclosures for the not-yet-wired export/deletion flows
 * (non-tappable, so they never dead-end the user), plus the app version.
 */

import { StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale } from '@/theme';

import {
  ComingSoonDisclosureRow,
  GroupedCard,
  SectionHeader,
  Separator,
  type SettingsColors,
} from './primitives';

export function DataAboutSection({
  appVersion,
  colors,
}: {
  appVersion: string;
  colors: SettingsColors;
}) {
  return (
    <>
      <SectionHeader title="DATA & ABOUT" colors={colors} />
      <GroupedCard colors={colors}>
        <ComingSoonDisclosureRow
          label="Export data"
          accessibilityLabel="Export data"
          note="Coming soon"
          colors={colors}
        />
        <Separator colors={colors} />
        <ComingSoonDisclosureRow
          label="Delete account"
          accessibilityLabel="Delete account"
          note="Coming soon"
          colors={colors}
        />
        <Separator colors={colors} />
        <View style={styles.aboutRow}>
          <Text style={[styles.aboutLabel, { color: colors.text }]}>Version</Text>
          <Text style={[styles.aboutValue, { color: colors.textMuted }]}>
            {appVersion}
          </Text>
        </View>
      </GroupedCard>
    </>
  );
}

const styles = StyleSheet.create({
  aboutRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  aboutLabel: {
    fontSize: typeScale.body,
  },
  aboutValue: {
    fontSize: typeScale.subhead,
  },
});
