/**
 * The ACCOUNT & SERVER section (FTY-203, extracted from SettingsScreen).
 *
 * Connected server, signed-in status, and the sign-out action.
 *
 * The Server row is editable (FTY-405): tapping it opens an inline editor for
 * the API base URL — the same control the connect screen offers, living where a
 * self-hoster looks for it later. The change is destructive to the session (a
 * token from one server is meaningless on another), so it resolves in two calm,
 * in-place beats: validate + probe, then an explicit confirmation that states
 * the sign-out before it happens. No navigation, no dialog — the card resolves
 * where the user is looking. The lifecycle lives in `useServerBaseUrlEditor`;
 * this file stays presentational.
 */

import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { spacing, typeScale, radius } from '@/theme';
import type { SessionRecord } from '@/state/session';

import {
  DisclosureRow,
  EditCard,
  EditFieldLabel,
  GroupedCard,
  InlineError,
  SectionHeader,
  Separator,
  type SettingsColors,
} from './primitives';
import type { ServerBaseUrlEditor } from './useServerBaseUrlEditor';

export function AccountSection({
  session,
  onSignOut,
  server,
  colors,
}: {
  session: SessionRecord;
  onSignOut: () => void;
  server: ServerBaseUrlEditor;
  colors: SettingsColors;
}) {
  const probing = server.phase === 'probing';

  return (
    <>
      <SectionHeader title="ACCOUNT & SERVER" colors={colors} />
      <GroupedCard colors={colors}>
        <DisclosureRow
          label="Server"
          value={server.currentBaseUrl}
          onPress={server.open}
          colors={colors}
          accessibilityLabel={`Server: ${server.currentBaseUrl}`}
          accessibilityHint="Double-tap to change your server address"
        />
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

      {/* Server address editor — enter/probe an address (FTY-405). */}
      {(server.phase === 'editing' || probing) && (
        <EditCard colors={colors} testID="server-url-edit-card">
          <EditFieldLabel colors={colors}>Server address</EditFieldLabel>
          <TextInput
            testID="server-url-input"
            accessibilityLabel="Server address"
            value={server.draft}
            onChangeText={server.setDraft}
            onSubmitEditing={() => void server.submit()}
            placeholder="https://slacks.example.com"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="off"
            inputMode="url"
            keyboardType="url"
            returnKeyType="go"
            editable={!probing}
            style={[
              styles.urlInput,
              {
                backgroundColor: colors.surface,
                color: colors.text,
                borderColor:
                  server.error !== null ? colors.coral : colors.separator,
              },
            ]}
          />
          <Text style={[styles.note, { color: colors.textSecondary }]}>
            Changing your server signs you out — your account lives on the server
            it was created on.
          </Text>
          {server.error !== null && (
            <InlineError
              message={server.error}
              colors={colors}
              testID="server-url-error"
            />
          )}
          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Use default server address"
              onPress={server.useDefault}
              disabled={probing}
              style={[
                styles.button,
                { backgroundColor: colors.controlBackground },
              ]}
            >
              <Text style={[styles.buttonLabel, { color: colors.textSecondary }]}>
                Use default
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel server address change"
              onPress={server.cancel}
              disabled={probing}
              style={[
                styles.button,
                { backgroundColor: colors.controlBackground },
              ]}
            >
              <Text style={[styles.buttonLabel, { color: colors.textSecondary }]}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Check server address"
              accessibilityState={{ disabled: probing }}
              disabled={probing}
              onPress={() => void server.submit()}
              style={[
                styles.button,
                { backgroundColor: colors.accent, opacity: probing ? 0.5 : 1 },
              ]}
            >
              <Text
                style={[styles.buttonLabel, { color: colors.accentForeground }]}
              >
                {probing ? 'Checking…' : 'Continue'}
              </Text>
            </Pressable>
          </View>
        </EditCard>
      )}

      {/* Confirmation — the probe succeeded; state the cost before paying it. */}
      {server.phase === 'confirm' && server.pending !== null && (
        <EditCard colors={colors} testID="server-url-confirm-card">
          <EditFieldLabel colors={colors}>Switch server</EditFieldLabel>
          <Text style={[styles.confirmBody, { color: colors.text }]}>
            {`${server.pending} is reachable. Switching signs you out — sign in again on the new server.`}
          </Text>
          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel server address change"
              onPress={server.cancel}
              style={[
                styles.button,
                { backgroundColor: colors.controlBackground },
              ]}
            >
              <Text style={[styles.buttonLabel, { color: colors.textSecondary }]}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Switch server and sign out"
              onPress={() => void server.confirmSwitch()}
              style={[styles.button, { backgroundColor: colors.accent }]}
            >
              <Text
                style={[styles.buttonLabel, { color: colors.accentForeground }]}
              >
                Switch & sign out
              </Text>
            </Pressable>
          </View>
        </EditCard>
      )}
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
  urlInput: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    fontSize: typeScale.body,
    minHeight: 44,
  },
  note: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
    lineHeight: 18,
  },
  confirmBody: {
    fontSize: typeScale.subhead,
    lineHeight: 20,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
    justifyContent: 'flex-end',
  },
  button: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonLabel: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
  },
});
