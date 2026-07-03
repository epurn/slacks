/**
 * The ACCOUNT & SERVER section (FTY-203, extracted from SettingsScreen).
 *
 * Connected server, signed-in status, and the sign-out action.
 */

import { Pressable, StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale } from '@/theme';
import type { SessionRecord } from '@/state/session';

import {
  GroupedCard,
  SectionHeader,
  Separator,
  type SettingsColors,
} from './primitives';

export function AccountSection({
  session,
  onSignOut,
  colors,
}: {
  session: SessionRecord;
  onSignOut: () => void;
  colors: SettingsColors;
}) {
  return (
    <>
      <SectionHeader title="ACCOUNT & SERVER" colors={colors} />
      <GroupedCard colors={colors}>
        <View style={styles.accountRow}>
          <Text style={[styles.accountLabel, { color: colors.textSecondary }]}>
            Server
          </Text>
          <Text
            style={[styles.accountValue, { color: colors.text }]}
            numberOfLines={1}
            accessibilityLabel={`Connected server: ${session.serverUrl}`}
          >
            {session.serverUrl}
          </Text>
        </View>
        <Separator colors={colors} />
        <View style={styles.accountRow}>
          <Text style={[styles.accountLabel, { color: colors.textSecondary }]}>
            Status
          </Text>
          <Text
            style={[styles.accountValue, { color: colors.text }]}
            accessibilityLabel="Status: Signed in"
          >
            Signed in
          </Text>
        </View>
        <Separator colors={colors} />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Sign out"
          onPress={onSignOut}
          style={styles.signOutRow}
        >
          <Text style={[styles.signOutLabel, { color: colors.coral }]}>
            Sign out
          </Text>
        </Pressable>
      </GroupedCard>
    </>
  );
}

const styles = StyleSheet.create({
  accountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    minHeight: 44,
  },
  accountLabel: {
    fontSize: typeScale.subhead,
    width: 60,
  },
  accountValue: {
    fontSize: typeScale.subhead,
    flex: 1,
    textAlign: 'right',
  },
  signOutRow: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 44,
    justifyContent: 'center',
  },
  signOutLabel: {
    fontSize: typeScale.body,
    fontWeight: '500',
  },
});
