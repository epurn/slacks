/**
 * Profile / Settings screen — "Control panel for your numbers" (FTY-102).
 *
 * Opens from the header gear as a native grouped settings screen. Sections:
 *   YOU         — goal, calorie target (with provenance + override + reset),
 *                 macro targets (same treatment)
 *   BODY        — weight, height, birth year, metabolic formula (body metrics)
 *   PREFERENCES — units, appearance (Light/Dark/System), weigh-in cadence
 *   ACCOUNT & SERVER — session state, server, sign out
 *   DATA & ABOUT     — export/deletion entry rows, about/version
 *
 * This file is the screen shell: it resolves theme/insets/navigation and wires
 * the `useSettingsController` state to the focused section components under
 * `components/settings/`. Editing goal/pace or any body metric triggers a
 * recompute and surfaces the new target via the mini target-reveal; every
 * calorie/macro number shows its provenance and carries a Reset affordance when
 * overridden — all owned by those sections and the controller (FTY-203).
 *
 * Privacy: sensitive figures (targets, macros, body metrics) are never written
 * to logs or error messages — errors carry only the HTTP status and action.
 */

import { useCallback, useRef } from 'react';
import { ScrollView, View, type LayoutChangeEvent } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { useTheme, spacing } from '@/theme';

import {
  useSettingsController,
  type SettingsControllerProps,
} from './settings/useSettingsController';
import { YouSection } from './settings/YouSection';
import { BodySection } from './settings/BodySection';
import { PreferencesSection } from './settings/PreferencesSection';
import { AccountSection } from './settings/AccountSection';
import { DataAboutSection } from './settings/DataAboutSection';
import {
  LoadErrorState,
  LoadingState,
  SignedOutState,
} from './settings/StateScreens';

export interface SettingsScreenProps extends SettingsControllerProps {
  /** App version string for the About row. */
  appVersion?: string;
}

export function SettingsScreen({
  appVersion = '1.0.0',
  ...controllerProps
}: SettingsScreenProps = {}) {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const c = useSettingsController(controllerProps);
  const { session } = c;

  // E2E-only visual-review seam (FTY-267): the appearance control sits below the
  // fold, so the `settings.appearance` preset scrolls straight to it on layout
  // instead of needing a simulated scroll gesture. `visualReviewSubState` is
  // always `null` outside E2E mode, so this scroll never fires in release/dev
  // builds.
  const scrollRef = useRef<ScrollView>(null);
  const handlePreferencesLayout = useCallback(
    (e: LayoutChangeEvent) => {
      if (c.visualReviewSubState !== 'appearance') return;
      scrollRef.current?.scrollTo({ y: e.nativeEvent.layout.y, animated: false });
    },
    [c.visualReviewSubState],
  );

  if (!session) {
    return (
      <SignedOutState
        colors={colors}
        insetTop={insets.top}
        onSignIn={() => router.replace('/signin')}
      />
    );
  }

  if (c.loading) {
    return <LoadingState colors={colors} insetTop={insets.top} />;
  }

  if (c.loadError) {
    return (
      <LoadErrorState colors={colors} insetTop={insets.top} message={c.loadError} />
    );
  }

  return (
    <ScrollView
      ref={scrollRef}
      style={{ flex: 1, backgroundColor: colors.surface }}
      // The native large-title header (configured on the /profile route) owns the
      // top inset: `automatic` insets content below the bar and drives the
      // large-title collapse + frost-on-scroll, so we never hand-pad the status-bar
      // height here (that magic number breaks across devices — FTY-182).
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={{
        paddingBottom: insets.bottom + 32,
        paddingHorizontal: spacing.base,
      }}
      keyboardShouldPersistTaps="handled"
    >
      <YouSection c={c} colors={colors} />
      <BodySection c={c} colors={colors} />
      <View onLayout={handlePreferencesLayout}>
        <PreferencesSection c={c} colors={colors} />
      </View>
      <AccountSection
        session={session}
        onSignOut={() => void c.handleSignOut()}
        colors={colors}
      />
      <DataAboutSection appVersion={appVersion} colors={colors} />
    </ScrollView>
  );
}
