/**
 * Full-screen guard states for Settings (FTY-203, extracted from SettingsScreen):
 * signed-out, loading, and load-error. Each centres a calm message; the
 * signed-out state offers a real way into sign-in rather than dead-ending.
 */

import { StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui/Button';
import { spacing, typeScale } from '@/theme';

import type { SettingsColors } from './primitives';

export function SignedOutState({
  colors,
  insetTop,
  onSignIn,
}: {
  colors: SettingsColors;
  insetTop: number;
  onSignIn: () => void;
}) {
  return (
    <View
      style={[
        styles.center,
        { backgroundColor: colors.surface, paddingTop: insetTop + 24 },
      ]}
    >
      <Text style={[styles.signInTitle, { color: colors.text }]}>
        Sign in to access settings
      </Text>
      <Text style={[styles.signInBody, { color: colors.textSecondary }]}>
        Your profile and targets are stored privately. Sign in to view and edit
        them.
      </Text>
      <Button label="Sign in" onPress={onSignIn} style={styles.signInAction} />
    </View>
  );
}

export function LoadingState({
  colors,
  insetTop,
}: {
  colors: SettingsColors;
  insetTop: number;
}) {
  return (
    <View
      style={[
        styles.center,
        { backgroundColor: colors.surface, paddingTop: insetTop + 24 },
      ]}
    >
      <Text
        style={[styles.signInBody, { color: colors.textMuted }]}
        accessibilityLabel="Loading your settings"
      >
        Loading…
      </Text>
    </View>
  );
}

export function LoadErrorState({
  colors,
  insetTop,
  message,
}: {
  colors: SettingsColors;
  insetTop: number;
  message: string;
}) {
  return (
    <View
      style={[
        styles.center,
        { backgroundColor: colors.surface, paddingTop: insetTop + 24 },
      ]}
    >
      <Text style={[styles.signInBody, { color: colors.coral }]} accessibilityRole="alert">
        {message}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  signInTitle: {
    fontSize: typeScale.title3,
    fontWeight: '700',
    textAlign: 'center',
  },
  signInBody: {
    fontSize: typeScale.subhead,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  signInAction: {
    marginTop: spacing.lg,
  },
});
