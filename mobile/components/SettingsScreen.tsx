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
 * Editing goal/pace or any body metric triggers a recompute and surfaces the
 * new target via a mini target-reveal. Every calorie/macro number shows its
 * provenance ("└ from your goal + metrics" vs. "✎ set by you") and carries a
 * Reset affordance when overridden.
 *
 * Privacy: sensitive figures (targets, macros, body metrics) are never written
 * to logs or error messages — errors carry only the HTTP status and action.
 */

import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {
  AccessibilityInfo,
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { Button } from '@/components/ui/Button';
import {
  getTarget,
  createGoal,
  getActiveGoalDirection,
  setTargetOverride,
  resetTargetOverride,
  GoalsApiError,
  type GoalDirection,
  type GoalTargetRequest,
  type GoalTargetResponse,
  type OverridableTargetKey,
  type PacePreset,
  type TargetOverridePayload,
} from '@/api/goals';
import { getProfile, putProfile, ProfileApiError } from '@/api/profile';
import { useGoalDirectionController } from '@/state/goalDirection';
import {
  CADENCE_OPTIONS,
  DEFAULT_CADENCE,
  applyReminderSettings,
  type CadenceStore,
  type NotificationsAdapter,
  type WeighInCadence,
} from '@/state/reminderScheduler';
import { fileCadenceStore, expoNotificationsAdapter } from '@/state/cadenceAdapter';
import type { AppSettingsStore } from '@/state/appSettings';
import { fileAppSettingsStore } from '@/state/appSettings';
import {
  METABOLIC_FORMULA_OPTIONS,
  cmToMeters,
  feetInchesToMeters,
  metersToFeetInches,
  kilograms,
  poundsToKilograms,
  type MetabolicFormula,
  type UnitsPreference,
} from '@/state/profile';
import type { Session } from '@/state/session';
import { toApiSession, useSession, useSessionController } from '@/state/session';
import {
  useTheme,
  spacing,
  typeScale,
  radius,
  type ColorSchemeOverride,
} from '@/theme';
import type { TargetReadModel } from '@/api/dailySummary';
import type { ProfileDTO } from '@/api/profile';
import { goalSummaryDetail } from './settingsGoalSummary';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

const APPEARANCE_OPTIONS: readonly { value: ColorSchemeOverride; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

const SETTINGS_METABOLIC_FORMULA_COPY: Record<
  MetabolicFormula,
  { readonly label: string; readonly description: string }
> = {
  mifflin_st_jeor_plus5: {
    label: 'Higher calorie baseline',
    description:
      'Uses the Mifflin-St Jeor +5 baseline, giving a slightly higher resting burn estimate.',
  },
  mifflin_st_jeor_minus161: {
    label: 'Lower calorie baseline',
    description:
      'Uses the Mifflin-St Jeor -161 baseline, giving a lower resting burn estimate.',
  },
};

function settingsFormulaCopy(value?: MetabolicFormula | string | null) {
  if (
    value === 'mifflin_st_jeor_plus5' ||
    value === 'mifflin_st_jeor_minus161'
  ) {
    return SETTINGS_METABOLIC_FORMULA_COPY[value];
  }
  return null;
}

/** A client-side validation failure on body-metric input (carries display copy). */
class InvalidBodyMetric extends Error {}

/**
 * A user-facing message for a failed save/reset. The API error classes already
 * carry only non-sensitive, status-derived copy (never target numbers), so they
 * are safe to surface; anything else falls back to a generic line.
 */
function actionErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof GoalsApiError || err instanceof ProfileApiError) {
    return err.message;
  }
  return fallback;
}

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────

export interface SettingsScreenProps {
  /** Injectable session for tests. When omitted, the live session is used. */
  session?: Session;
  /** Injectable API functions for testing. */
  getTargetFn?: typeof getTarget;
  getProfileFn?: typeof getProfile;
  putProfileFn?: typeof putProfile;
  createGoalFn?: typeof createGoal;
  getActiveGoalDirectionFn?: typeof getActiveGoalDirection;
  setTargetOverrideFn?: typeof setTargetOverride;
  resetTargetOverrideFn?: typeof resetTargetOverride;
  /** Injectable on-device settings stores. */
  settingsStore?: AppSettingsStore;
  cadenceStore?: CadenceStore;
  notificationsAdapter?: NotificationsAdapter;
  /** App version string for the About row. */
  appVersion?: string;
  /**
   * Callback invoked when the user changes the appearance preference so the
   * root ThemeProvider can be updated. Injectable for tests.
   */
  onAppearanceChange?: (v: ColorSchemeOverride) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export function SettingsScreen({
  session: sessionOverride,
  getTargetFn = getTarget,
  getProfileFn = getProfile,
  putProfileFn = putProfile,
  createGoalFn = createGoal,
  getActiveGoalDirectionFn = getActiveGoalDirection,
  setTargetOverrideFn = setTargetOverride,
  resetTargetOverrideFn = resetTargetOverride,
  settingsStore = fileAppSettingsStore,
  cadenceStore = fileCadenceStore,
  notificationsAdapter = expoNotificationsAdapter,
  appVersion = '1.0.0',
  onAppearanceChange,
}: SettingsScreenProps = {}) {
  const liveSession = useSession();
  const sessionController = useSessionController();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const {
    goalDirection: sessionGoalDirection,
    setGoalDirection: setKnownGoalDirection,
  } = useGoalDirectionController();

  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  // Data state
  const [profile, setProfile] = useState<ProfileDTO | null>(null);
  const [target, setTarget] = useState<TargetReadModel | null>(null);
  const [goalDirection, setGoalDirection] = useState<GoalDirection | null>(null);
  const [goalPace, setGoalPace] = useState<PacePreset | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [noTarget, setNoTarget] = useState(false);

  // Preferences state
  const [appearance, setAppearance] = useState<ColorSchemeOverride>('system');
  const [cadence, setCadence] = useState<WeighInCadence>(DEFAULT_CADENCE);

  // Edit states
  const [editingGoal, setEditingGoal] = useState(false);
  const [editDirection, setEditDirection] = useState<GoalDirection>('loss');
  const [editPace, setEditPace] = useState<PacePreset>('steady');
  const [goalSaving, setGoalSaving] = useState(false);

  const [editingBodyMetric, setEditingBodyMetric] = useState<
    'weight' | 'height' | 'birthYear' | 'formula' | null
  >(null);
  const [bodyEditValue, setBodyEditValue] = useState('');
  // Imperial height is captured as feet (bodyEditValue) + inches (this) so the
  // editor matches the "ft + in" display and never silently drops the inches.
  const [bodyEditInches, setBodyEditInches] = useState('');
  const [bodyEditFormula, setBodyEditFormula] = useState<MetabolicFormula | null>(null);
  const [bodySaving, setBodySaving] = useState(false);

  const [editingCalorieOverride, setEditingCalorieOverride] = useState(false);
  const [editingMacroOverride, setEditingMacroOverride] = useState<
    'protein_g' | 'carbs_g' | 'fat_g' | null
  >(null);
  const [overrideValue, setOverrideValue] = useState('');
  const [overrideSaving, setOverrideSaving] = useState(false);

  // In-place feedback for a failed save/reset (status-derived, never sensitive).
  const [actionError, setActionError] = useState<string | null>(null);

  // Mini target-reveal
  const [revealTarget, setRevealTarget] = useState<TargetReadModel | null>(null);
  const [revealClamped, setRevealClamped] = useState(false);
  const [revealOpacity] = useState(() => new Animated.Value(0));

  // ── Load on mount ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!session) return;
    let active = true;
    const apiSession = toApiSession(session);

    void Promise.all([
      getProfileFn(apiSession),
      getTargetFn(apiSession).catch((e: { status?: number }) => {
        if (e && e.status === 404) return null;
        throw e;
      }),
      // Authoritative direction of the returning user's active goal so the
      // collapsed Goal row summarises the real goal on a cold load instead of
      // depending on an in-session edit. A load failure degrades to the
      // in-memory cross-screen direction rather than blocking settings.
      getActiveGoalDirectionFn(apiSession).catch(() => null),
      settingsStore.getAppearance(),
      cadenceStore.getCadence(),
    ])
      .then(([prof, tgt, dir, app, cad]) => {
        if (!active) return;
        setProfile(prof);
        if (tgt === null) {
          setNoTarget(true);
        } else {
          setTarget(tgt);
        }
        if (dir !== null) setGoalDirection(dir);
        setAppearance(app);
        setCadence(cad ?? DEFAULT_CADENCE);
      })
      .catch(() => {
        if (!active) return;
        setLoadError('Could not load your settings. Please try again.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [
    session,
    getProfileFn,
    getTargetFn,
    getActiveGoalDirectionFn,
    settingsStore,
    cadenceStore,
  ]);

  // ── Mini reveal animation ─────────────────────────────────────────────────

  const showReveal = useCallback(
    (tgt: TargetReadModel, clamped = false) => {
      setRevealTarget(tgt);
      setRevealClamped(clamped);
      revealOpacity.setValue(0);
      AccessibilityInfo.isReduceMotionEnabled().then((reduced) => {
        if (reduced) {
          revealOpacity.setValue(1);
        } else {
          Animated.timing(revealOpacity, {
            toValue: 1,
            duration: 300,
            useNativeDriver: true,
          }).start();
        }
      });
    },
    [revealOpacity],
  );

  // ── Goal edit handlers ────────────────────────────────────────────────────

  const currentGoalDirection = goalDirection ?? sessionGoalDirection;
  // Pace is known only from this session's own goal edit — it is never carried
  // on any read-model the client can fetch on a cold launch (`GET /goal`
  // recovers only the direction) and is never inferred from target numbers or
  // replayed from a local cache. Until the user edits the goal this session the
  // collapsed row summarises the real goal by its authoritative direction alone
  // rather than guessing or showing a possibly-stale pace.
  const currentGoalPace = goalPace;

  const openGoalEdit = useCallback(() => {
    setActionError(null);
    setEditDirection(currentGoalDirection ?? 'loss');
    setEditPace(currentGoalPace ?? 'steady');
    setEditingGoal(true);
  }, [currentGoalDirection, currentGoalPace]);

  // `faster` is a loss-only pace preset; `gain` rejects it (422). Clamp it back
  // to `steady` when leaving `loss` so the editor can never submit the
  // structurally-invalid {direction: 'gain', pace: 'faster'} the backend
  // guarantees to reject. See docs/contracts/goals-target-reveal.md.
  const handleDirectionChange = useCallback((next: GoalDirection) => {
    setEditDirection(next);
    if (next !== 'loss') {
      setEditPace((prev) => (prev === 'faster' ? 'steady' : prev));
    }
  }, []);

  const handleSaveGoal = useCallback(async () => {
    if (!session) return;
    setGoalSaving(true);
    setActionError(null);
    const apiSession = toApiSession(session);
    const payload: GoalTargetRequest = {
      direction: editDirection,
      ...(editDirection !== 'maintain' ? { pace: editPace } : {}),
    };
    try {
      const reveal: GoalTargetResponse = await createGoalFn(apiSession, payload);
      const savedPace = editDirection !== 'maintain' ? editPace : null;
      setGoalDirection(reveal.target.direction);
      setKnownGoalDirection(reveal.target.direction);
      // The pace the user just chose upgrades the collapsed row to direction +
      // pace for the rest of this session. It is intentionally not persisted:
      // the goal itself round-tripped to the server (the authoritative store),
      // and replaying a cached pace on a later launch risks showing a stale
      // value if the goal is changed on another device.
      setGoalPace(savedPace);
      setEditingGoal(false);
      // Fetch the full read-model (reveal only has calories, not macros)
      const updatedTarget = await getTargetFn(apiSession);
      setTarget(updatedTarget);
      setNoTarget(false);
      showReveal(updatedTarget, reveal.clamp.clamped);
    } catch (err) {
      // The error is never logged (would expose sensitive context); a friendly,
      // status-derived line is surfaced in the open edit card instead.
      setActionError(actionErrorMessage(err, 'Could not save your goal. Please try again.'));
    } finally {
      setGoalSaving(false);
    }
  }, [
    session,
    editDirection,
    editPace,
    createGoalFn,
    getTargetFn,
    showReveal,
    setKnownGoalDirection,
  ]);

  // ── Body metric edit handlers ─────────────────────────────────────────────

  const openBodyEdit = useCallback(
    (metric: 'weight' | 'height' | 'birthYear' | 'formula') => {
      setActionError(null);
      setEditingBodyMetric(metric);
      setBodyEditValue('');
      setBodyEditInches('');
      if (profile && metric === 'formula') {
        setBodyEditFormula(
          (profile.metabolic_formula as MetabolicFormula | string) === 'mifflin_st_jeor_plus5'
            ? 'mifflin_st_jeor_plus5'
            : (profile.metabolic_formula as MetabolicFormula | string) === 'mifflin_st_jeor_minus161'
              ? 'mifflin_st_jeor_minus161'
              : null,
        );
      }
    },
    [profile],
  );

  const handleSaveBodyMetric = useCallback(async () => {
    if (!session || !profile) return;
    setBodySaving(true);
    setActionError(null);
    const apiSession = toApiSession(session);
    const isMetric = profile.units_preference === 'metric';

    try {
      const updates: Partial<{
        weight_kg: number;
        height_m: number;
        birth_year: number;
        metabolic_formula: MetabolicFormula;
      }> = {};

      if (editingBodyMetric === 'weight') {
        const raw = parseFloat(bodyEditValue);
        if (!isFinite(raw)) throw new InvalidBodyMetric('Enter a valid number.');
        updates.weight_kg = isMetric ? kilograms(raw) : poundsToKilograms(raw);
      } else if (editingBodyMetric === 'height') {
        if (isMetric) {
          const cm = parseFloat(bodyEditValue);
          if (!isFinite(cm)) throw new InvalidBodyMetric('Enter a valid number.');
          updates.height_m = cmToMeters(cm);
        } else {
          // Imperial height is feet + inches; inches default to 0 when blank.
          const feet = parseFloat(bodyEditValue);
          const inches = bodyEditInches.trim() === '' ? 0 : parseFloat(bodyEditInches);
          if (!isFinite(feet) || !isFinite(inches)) {
            throw new InvalidBodyMetric('Enter a valid number.');
          }
          updates.height_m = feetInchesToMeters(feet, inches);
        }
      } else if (editingBodyMetric === 'birthYear') {
        const year = parseInt(bodyEditValue, 10);
        if (!isFinite(year)) throw new InvalidBodyMetric('Enter a valid year.');
        updates.birth_year = year;
      } else if (editingBodyMetric === 'formula' && bodyEditFormula) {
        updates.metabolic_formula = bodyEditFormula;
      }

      if (Object.keys(updates).length === 0) {
        setEditingBodyMetric(null);
        return;
      }

      const updatedProfile = await putProfileFn(apiSession, {
        ...updates,
        units_preference: profile.units_preference,
        timezone: profile.timezone,
      } as Parameters<typeof putProfile>[1]);
      setProfile(updatedProfile);
      setEditingBodyMetric(null);

      // Read back the recomputed target (may or may not have changed)
      const updatedTarget = await getTargetFn(apiSession).catch(() => null);
      if (updatedTarget) {
        setTarget(updatedTarget);
        setNoTarget(false);
        showReveal(updatedTarget);
      }
    } catch (err) {
      // Error not logged to avoid sensitive context. Keep the edit card open and
      // explain in place — a validation message for bad input, else a friendly
      // status-derived line — instead of silently closing.
      setActionError(
        err instanceof InvalidBodyMetric
          ? err.message
          : actionErrorMessage(err, 'Could not save. Please try again.'),
      );
    } finally {
      setBodySaving(false);
    }
  }, [
    session,
    profile,
    editingBodyMetric,
    bodyEditValue,
    bodyEditInches,
    bodyEditFormula,
    putProfileFn,
    getTargetFn,
    showReveal,
  ]);

  // ── Target override / reset handlers ─────────────────────────────────────

  const handleSaveOverride = useCallback(async () => {
    if (!session) return;
    setOverrideSaving(true);
    setActionError(null);
    const apiSession = toApiSession(session);
    const val = parseInt(overrideValue, 10);
    if (!isFinite(val)) {
      setActionError('Enter a valid number.');
      setOverrideSaving(false);
      return;
    }

    const payload: TargetOverridePayload = editingCalorieOverride
      ? { calorie_target_kcal: val }
      : editingMacroOverride === 'protein_g'
        ? { protein_target_g: val }
        : editingMacroOverride === 'carbs_g'
          ? { carbs_target_g: val }
          : { fat_target_g: val };

    try {
      const updatedTarget = await setTargetOverrideFn(apiSession, payload);
      setTarget(updatedTarget);
      setEditingCalorieOverride(false);
      setEditingMacroOverride(null);
    } catch (err) {
      // Error not logged. Keep the override card open and explain in place — the
      // expected 422 (out-of-band value) and 404 paths now close the loop.
      setActionError(
        actionErrorMessage(err, 'Could not save your override. Please try again.'),
      );
    } finally {
      setOverrideSaving(false);
    }
  }, [
    session,
    overrideValue,
    editingCalorieOverride,
    editingMacroOverride,
    setTargetOverrideFn,
  ]);

  const handleReset = useCallback(
    async (targets: OverridableTargetKey[]) => {
      if (!session) return;
      setActionError(null);
      const apiSession = toApiSession(session);
      try {
        const updatedTarget = await resetTargetOverrideFn(apiSession, targets);
        setTarget(updatedTarget);
      } catch (err) {
        // Error not logged; surfaced in place near the targets.
        setActionError(
          actionErrorMessage(err, 'Could not reset your target. Please try again.'),
        );
      }
    },
    [session, resetTargetOverrideFn],
  );

  // ── Preferences handlers ──────────────────────────────────────────────────

  const handleAppearanceChange = useCallback(
    async (v: ColorSchemeOverride) => {
      setAppearance(v);
      await settingsStore.setAppearance(v);
      onAppearanceChange?.(v);
    },
    [settingsStore, onAppearanceChange],
  );

  const handleCadenceChange = useCallback(
    async (v: WeighInCadence) => {
      setCadence(v);
      const lastDate = await cadenceStore.getLastWeighInDate();
      await applyReminderSettings(v, lastDate, cadenceStore, notificationsAdapter);
    },
    [cadenceStore, notificationsAdapter],
  );

  const handleUnitsChange = useCallback(
    async (v: UnitsPreference) => {
      if (!session || !profile) return;
      const apiSession = toApiSession(session);
      try {
        const updated = await putProfileFn(apiSession, {
          height_m: profile.height_m,
          weight_kg: profile.weight_kg,
          birth_year: profile.birth_year,
          metabolic_formula: profile.metabolic_formula as MetabolicFormula,
          units_preference: v,
          timezone: profile.timezone,
        } as Parameters<typeof putProfile>[1]);
        setProfile(updated);
      } catch {
        // Error not logged
      }
    },
    [session, profile, putProfileFn],
  );

  // ── Sign out ──────────────────────────────────────────────────────────────

  const handleSignOut = useCallback(async () => {
    await sessionController.signOut();
  }, [sessionController]);

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  const isMetric = profile?.units_preference === 'metric';

  const goalIsActive = !noTarget && target !== null;
  const goalDetail = goalIsActive
    ? goalSummaryDetail(currentGoalDirection, currentGoalPace)
    : 'Not set';
  const formulaCopy = settingsFormulaCopy(profile?.metabolic_formula);

  if (!session) {
    return (
      <View
        style={[
          styles.center,
          { backgroundColor: colors.surface, paddingTop: insets.top + 24 },
        ]}
      >
        <Text style={[styles.signInTitle, { color: colors.text }]}>
          Sign in to access settings
        </Text>
        <Text style={[styles.signInBody, { color: colors.textSecondary }]}>
          Your profile and targets are stored privately. Sign in to view and
          edit them.
        </Text>
        <Button
          label="Sign in"
          onPress={() => router.replace('/signin')}
          style={styles.signInAction}
        />
      </View>
    );
  }

  if (loading) {
    return (
      <View
        style={[
          styles.center,
          { backgroundColor: colors.surface, paddingTop: insets.top + 24 },
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

  if (loadError) {
    return (
      <View
        style={[
          styles.center,
          { backgroundColor: colors.surface, paddingTop: insets.top + 24 },
        ]}
      >
        <Text
          style={[styles.signInBody, { color: colors.coral }]}
          accessibilityRole="alert"
        >
          {loadError}
        </Text>
      </View>
    );
  }

  return (
    <ScrollView
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
      {/* ── YOU ──────────────────────────────────────────────────────── */}
      <SectionHeader title="YOU" colors={colors} />

      {/* Goal row */}
      <GroupedCard colors={colors}>
        <SettingsRow
          label="Goal"
          value={goalDetail}
          onPress={openGoalEdit}
          accessibilityLabel={`Goal: ${goalDetail}`}
          accessibilityHint="Double-tap to edit your goal"
          colors={colors}
        />
      </GroupedCard>

      {/* Goal edit inline */}
      {editingGoal && (
        <EditCard colors={colors} testID="goal-edit-card">
          <Text style={[styles.editLabel, { color: colors.textSecondary }]}>
            Direction
          </Text>
          <Segmented<GoalDirection>
            options={[
              { value: 'loss', label: 'Lose' },
              { value: 'maintain', label: 'Maintain' },
              { value: 'gain', label: 'Gain' },
            ]}
            selected={editDirection}
            onSelect={handleDirectionChange}
            accessibilityLabel="Goal direction"
            colors={colors}
          />
          {editDirection !== 'maintain' && (
            <>
              <Text
                style={[
                  styles.editLabel,
                  { color: colors.textSecondary, marginTop: spacing.sm },
                ]}
              >
                Pace
              </Text>
              <Segmented<PacePreset>
                options={[
                  { value: 'gentle', label: 'Gentle' },
                  { value: 'steady', label: 'Steady' },
                  ...(editDirection === 'loss'
                    ? [{ value: 'faster' as PacePreset, label: 'Faster' }]
                    : []),
                ]}
                selected={editPace}
                onSelect={setEditPace}
                accessibilityLabel="Goal pace"
                colors={colors}
              />
            </>
          )}
          {actionError && (
            <InlineError message={actionError} colors={colors} testID="goal-edit-error" />
          )}
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel goal edit"
              onPress={() => {
                setActionError(null);
                setEditingGoal(false);
              }}
              style={[styles.editButton, { backgroundColor: colors.controlBackground }]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.textSecondary }]}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Save goal"
              accessibilityState={{ disabled: goalSaving }}
              disabled={goalSaving}
              onPress={() => void handleSaveGoal()}
              style={[
                styles.editButton,
                { backgroundColor: colors.accent, opacity: goalSaving ? 0.5 : 1 },
              ]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.accentForeground }]}>
                {goalSaving ? 'Saving…' : 'Save'}
              </Text>
            </Pressable>
          </View>
        </EditCard>
      )}

      {/* Calorie target */}
      <GroupedCard colors={colors} style={{ marginTop: spacing.xs }}>
        {noTarget || !target ? (
          <View style={styles.noTargetRow}>
            <Text
              style={[styles.noTargetText, { color: colors.textMuted }]}
              accessibilityLabel="No calorie target. Set your goal and body metrics to see your target."
            >
              Set your goal + metrics to see your target
            </Text>
          </View>
        ) : (
          <>
            <TargetRow
              label="Calories"
              unit="kcal"
              component={target.calories}
              onOverride={() => {
                setActionError(null);
                setEditingCalorieOverride(true);
                setOverrideValue(String(target.calories.effective));
              }}
              onReset={() => void handleReset(['calories'])}
              colors={colors}
              testID="calorie-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Protein"
              unit="g"
              component={target.protein_g}
              onOverride={() => {
                setActionError(null);
                setEditingMacroOverride('protein_g');
                setOverrideValue(String(target.protein_g.effective));
              }}
              onReset={() => void handleReset(['protein'])}
              colors={colors}
              testID="protein-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Carbs"
              unit="g"
              component={target.carbs_g}
              onOverride={() => {
                setActionError(null);
                setEditingMacroOverride('carbs_g');
                setOverrideValue(String(target.carbs_g.effective));
              }}
              onReset={() => void handleReset(['carbs'])}
              colors={colors}
              testID="carbs-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Fat"
              unit="g"
              component={target.fat_g}
              onOverride={() => {
                setActionError(null);
                setEditingMacroOverride('fat_g');
                setOverrideValue(String(target.fat_g.effective));
              }}
              onReset={() => void handleReset(['fat'])}
              colors={colors}
              testID="fat-target-row"
            />
          </>
        )}
      </GroupedCard>

      {/* Action error not tied to an open editor (e.g. a failed reset) */}
      {actionError &&
        !editingGoal &&
        !editingBodyMetric &&
        !editingCalorieOverride &&
        !editingMacroOverride && (
          <InlineError
            message={actionError}
            colors={colors}
            testID="target-action-error"
            style={{ marginTop: spacing.xs }}
          />
        )}

      {/* Calorie override edit */}
      {editingCalorieOverride && (
        <OverrideEditCard
          label="Override calorie target (kcal)"
          value={overrideValue}
          onChangeText={setOverrideValue}
          saving={overrideSaving}
          error={actionError}
          onSave={() => void handleSaveOverride()}
          onCancel={() => {
            setActionError(null);
            setEditingCalorieOverride(false);
          }}
          colors={colors}
          testID="calorie-override-edit"
        />
      )}

      {/* Macro override edit */}
      {editingMacroOverride && (
        <OverrideEditCard
          label={`Override ${editingMacroOverride.replace('_g', '')} target (g)`}
          value={overrideValue}
          onChangeText={setOverrideValue}
          saving={overrideSaving}
          error={actionError}
          onSave={() => void handleSaveOverride()}
          onCancel={() => {
            setActionError(null);
            setEditingMacroOverride(null);
          }}
          colors={colors}
          testID="macro-override-edit"
        />
      )}

      {/* Mini target-reveal */}
      {revealTarget && (
        <Animated.View
          style={[
            styles.revealCard,
            {
              backgroundColor: colors.surfaceRaised,
              borderRadius: radius.lg,
              opacity: revealOpacity,
            },
          ]}
          accessibilityLabel={`Updated targets: ${revealTarget.calories.effective} kcal calories, ${revealTarget.protein_g.effective} g protein, ${revealTarget.carbs_g.effective} g carbs, ${revealTarget.fat_g.effective} g fat${revealClamped ? '. Adjusted to a safe limit' : ''}`}
          testID="mini-target-reveal"
        >
          <Text style={[styles.revealTitle, { color: colors.textSecondary }]}>
            Updated targets
          </Text>
          <View style={styles.revealRow}>
            <RevealItem
              label="Cal"
              value={revealTarget.calories.effective}
              unit="kcal"
              clamped={revealClamped}
              colors={colors}
            />
            <RevealItem
              label="P"
              value={revealTarget.protein_g.effective}
              unit="g"
              clamped={false}
              colors={colors}
            />
            <RevealItem
              label="C"
              value={revealTarget.carbs_g.effective}
              unit="g"
              clamped={false}
              colors={colors}
            />
            <RevealItem
              label="F"
              value={revealTarget.fat_g.effective}
              unit="g"
              clamped={false}
              colors={colors}
            />
          </View>
          {revealClamped && (
            <Text
              style={[styles.revealClampNote, { color: colors.textMuted }]}
              testID="reveal-clamp-note"
            >
              * Adjusted to a safe limit
            </Text>
          )}
        </Animated.View>
      )}

      {/* ── BODY ─────────────────────────────────────────────────────── */}
      <SectionHeader title="BODY" colors={colors} />
      <GroupedCard colors={colors}>
        <BodyMetricRow
          label="Weight"
          value={
            profile?.weight_kg != null
              ? isMetric
                ? `${profile.weight_kg} kg`
                : `${Math.round(profile.weight_kg / 0.45359237)} lb`
              : '—'
          }
          onPress={() => openBodyEdit('weight')}
          colors={colors}
          accessibilityLabel={`Weight: ${profile?.weight_kg != null ? (isMetric ? `${profile.weight_kg} kilograms` : `${Math.round(profile.weight_kg / 0.45359237)} pounds`) : 'not set'}`}
          accessibilityHint="Double-tap to edit your weight"
        />
        <Separator colors={colors} />
        <BodyMetricRow
          label="Height"
          value={
            profile?.height_m != null
              ? isMetric
                ? `${Math.round(profile.height_m * 100)} cm`
                : `${metersToFeetInches(profile.height_m).feet} ft ${metersToFeetInches(profile.height_m).inches} in`
              : '—'
          }
          onPress={() => openBodyEdit('height')}
          colors={colors}
          accessibilityLabel={`Height: ${profile?.height_m != null ? (isMetric ? `${Math.round(profile.height_m * 100)} centimetres` : `${metersToFeetInches(profile.height_m).feet} feet ${metersToFeetInches(profile.height_m).inches} inches`) : 'not set'}`}
          accessibilityHint="Double-tap to edit your height"
        />
        <Separator colors={colors} />
        <BodyMetricRow
          label="Age"
          value={profile?.birth_year != null ? `Born ${profile.birth_year}` : '—'}
          onPress={() => openBodyEdit('birthYear')}
          colors={colors}
          accessibilityLabel={`Age: ${profile?.birth_year != null ? `birth year ${profile.birth_year}` : 'not set'}`}
          accessibilityHint="Double-tap to edit your birth year"
        />
        <Separator colors={colors} />
        <BodyMetricRow
          label="Calculation preference"
          value={formulaCopy?.label ?? '—'}
          onPress={() => openBodyEdit('formula')}
          colors={colors}
          accessibilityLabel={`Calculation preference: ${formulaCopy?.label ?? 'not set'}${formulaCopy ? `. ${formulaCopy.description}` : ''}`}
          accessibilityHint="Double-tap to change your metabolic formula"
        />
      </GroupedCard>

      {/* Body metric inline edit */}
      {editingBodyMetric && editingBodyMetric !== 'formula' && (
        <EditCard colors={colors} testID="body-metric-edit-card">
          <Text style={[styles.editLabel, { color: colors.textSecondary }]}>
            {editingBodyMetric === 'weight'
              ? `New weight (${isMetric ? 'kg' : 'lb'})`
              : editingBodyMetric === 'height'
                ? `New height (${isMetric ? 'cm' : 'ft + in'})`
                : 'Birth year'}
          </Text>
          <View style={styles.bodyEditInputs}>
            <TextInput
              accessibilityLabel={
                editingBodyMetric === 'weight'
                  ? `New weight in ${isMetric ? 'kilograms' : 'pounds'}`
                  : editingBodyMetric === 'height'
                    ? `New height in ${isMetric ? 'centimetres' : 'feet'}`
                    : 'New birth year'
              }
              value={bodyEditValue}
              onChangeText={setBodyEditValue}
              keyboardType="numeric"
              inputMode="numeric"
              style={[
                styles.overrideInput,
                styles.bodyEditInput,
                {
                  backgroundColor: colors.surface,
                  color: colors.text,
                  borderColor: colors.separator,
                },
              ]}
            />
            {editingBodyMetric === 'height' && !isMetric && (
              <TextInput
                accessibilityLabel="New height inches"
                value={bodyEditInches}
                onChangeText={setBodyEditInches}
                keyboardType="numeric"
                inputMode="numeric"
                placeholder="in"
                placeholderTextColor={colors.textMuted}
                style={[
                  styles.overrideInput,
                  styles.bodyEditInput,
                  {
                    backgroundColor: colors.surface,
                    color: colors.text,
                    borderColor: colors.separator,
                  },
                ]}
              />
            )}
          </View>
          {actionError && (
            <InlineError message={actionError} colors={colors} testID="body-edit-error" />
          )}
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel body metric edit"
              onPress={() => {
                setActionError(null);
                setEditingBodyMetric(null);
              }}
              style={[styles.editButton, { backgroundColor: colors.controlBackground }]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.textSecondary }]}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Save body metric"
              accessibilityState={{ disabled: bodySaving }}
              disabled={bodySaving}
              onPress={() => void handleSaveBodyMetric()}
              style={[
                styles.editButton,
                { backgroundColor: colors.accent, opacity: bodySaving ? 0.5 : 1 },
              ]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.accentForeground }]}>
                {bodySaving ? 'Saving…' : 'Save'}
              </Text>
            </Pressable>
          </View>
        </EditCard>
      )}

      {editingBodyMetric === 'formula' && (
        <EditCard colors={colors} testID="formula-edit-card">
          {METABOLIC_FORMULA_OPTIONS.map((opt) => {
            const selected = bodyEditFormula === opt.value;
            const copy = settingsFormulaCopy(opt.value);
            return (
              <Pressable
                key={opt.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${copy?.label ?? opt.label}. ${copy?.description ?? opt.description}`}
                onPress={() => setBodyEditFormula(opt.value)}
                style={[
                  styles.formulaChoice,
                  {
                    backgroundColor: colors.surfaceRaised,
                    borderColor: selected ? colors.accent : colors.separator,
                  },
                ]}
              >
                <Text
                  style={[
                    styles.formulaChoiceLabel,
                    { color: selected ? colors.accent : colors.text },
                  ]}
                >
                  {copy?.label ?? opt.label}
                </Text>
                <Text style={[styles.formulaChoiceDesc, { color: colors.textMuted }]}>
                  {copy?.description ?? opt.description}
                </Text>
              </Pressable>
            );
          })}
          {actionError && (
            <InlineError message={actionError} colors={colors} testID="formula-edit-error" />
          )}
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel formula edit"
              onPress={() => {
                setActionError(null);
                setEditingBodyMetric(null);
              }}
              style={[styles.editButton, { backgroundColor: colors.controlBackground }]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.textSecondary }]}>
                Cancel
              </Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Save calculation preference"
              accessibilityState={{ disabled: bodySaving }}
              disabled={bodySaving}
              onPress={() => void handleSaveBodyMetric()}
              style={[
                styles.editButton,
                { backgroundColor: colors.accent, opacity: bodySaving ? 0.5 : 1 },
              ]}
            >
              <Text style={[styles.editButtonLabel, { color: colors.accentForeground }]}>
                {bodySaving ? 'Saving…' : 'Save'}
              </Text>
            </Pressable>
          </View>
        </EditCard>
      )}

      {/* ── PREFERENCES ──────────────────────────────────────────────── */}
      <SectionHeader title="PREFERENCES" colors={colors} />
      <GroupedCard colors={colors}>
        <View style={styles.prefRow}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>Units</Text>
          <Segmented<UnitsPreference>
            options={[
              { value: 'metric', label: 'Metric' },
              { value: 'imperial', label: 'Imperial' },
            ]}
            selected={profile?.units_preference ?? 'metric'}
            onSelect={(v) => void handleUnitsChange(v)}
            accessibilityLabel="Units preference"
            colors={colors}
            compact
          />
        </View>
        <Separator colors={colors} />
        <View style={styles.prefRow}>
          <Text style={[styles.prefLabel, { color: colors.text }]}>Appearance</Text>
          <Segmented<ColorSchemeOverride>
            options={APPEARANCE_OPTIONS}
            selected={appearance}
            onSelect={(v) => void handleAppearanceChange(v)}
            accessibilityLabel="Appearance"
            colors={colors}
            compact
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
          <Segmented<WeighInCadence>
            options={CADENCE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
            selected={cadence}
            onSelect={(v) => void handleCadenceChange(v)}
            accessibilityLabel="Weigh-in cadence"
            colors={colors}
          />
        </View>
      </GroupedCard>

      {/* ── ACCOUNT & SERVER ─────────────────────────────────────────── */}
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
          onPress={() => void handleSignOut()}
          style={styles.signOutRow}
        >
          <Text style={[styles.signOutLabel, { color: colors.coral }]}>
            Sign out
          </Text>
        </Pressable>
      </GroupedCard>

      {/* ── DATA & ABOUT ─────────────────────────────────────────────── */}
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
    </ScrollView>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function SectionHeader({
  title,
  colors,
}: {
  title: string;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <Text
      style={[styles.sectionHeader, { color: colors.textMuted }]}
      accessibilityRole="header"
    >
      {title}
    </Text>
  );
}

function GroupedCard({
  children,
  colors,
  style,
}: {
  children: ReactNode;
  colors: ReturnType<typeof useTheme>['colors'];
  style?: object;
}) {
  return (
    <View
      style={[
        styles.groupedCard,
        { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
        style,
      ]}
    >
      {children}
    </View>
  );
}

function EditCard({
  children,
  colors,
  testID,
}: {
  children: ReactNode;
  colors: ReturnType<typeof useTheme>['colors'];
  testID?: string;
}) {
  return (
    <View
      testID={testID}
      style={[
        styles.editCard,
        { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
      ]}
    >
      {children}
    </View>
  );
}

function Separator({ colors }: { colors: ReturnType<typeof useTheme>['colors'] }) {
  return (
    <View style={[styles.separator, { backgroundColor: colors.separator }]} />
  );
}

/** A calm, in-place error line for a failed save/reset (no sensitive context). */
function InlineError({
  message,
  colors,
  testID,
  style,
}: {
  message: string;
  colors: ReturnType<typeof useTheme>['colors'];
  testID?: string;
  style?: object;
}) {
  return (
    <Text
      testID={testID}
      accessibilityRole="alert"
      style={[styles.inlineError, { color: colors.coral }, style]}
    >
      {message}
    </Text>
  );
}

function SettingsRow({
  label,
  value,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  colors,
}: {
  label: string;
  value: string;
  onPress?: () => void;
  accessibilityLabel: string;
  accessibilityHint?: string;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      style={styles.settingsRow}
    >
      <Text style={[styles.rowLabel, { color: colors.text }]}>{label}</Text>
      <View style={styles.rowRight}>
        <Text style={[styles.rowValue, { color: colors.textSecondary }]}>{value}</Text>
        <Text style={[styles.rowChevron, { color: colors.textMuted }]}>›</Text>
      </View>
    </Pressable>
  );
}

function BodyMetricRow({
  label,
  value,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  colors,
}: {
  label: string;
  value: string;
  onPress: () => void;
  accessibilityLabel: string;
  accessibilityHint: string;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      style={styles.settingsRow}
    >
      <Text style={[styles.rowLabel, { color: colors.text }]}>{label}</Text>
      <View style={styles.rowRight}>
        <Text style={[styles.rowValue, { color: colors.textSecondary }]}>{value}</Text>
        <Text style={[styles.rowChevron, { color: colors.textMuted }]}>›</Text>
      </View>
    </Pressable>
  );
}

function ComingSoonDisclosureRow({
  label,
  accessibilityLabel,
  colors,
  note,
}: {
  label: string;
  accessibilityLabel: string;
  colors: ReturnType<typeof useTheme>['colors'];
  /** Trailing status text (e.g. "Coming soon") for a not-yet-wired row. */
  note: string;
}) {
  return (
    <View
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: true }}
      style={[styles.settingsRow, styles.comingSoonRow]}
    >
      <Text style={[styles.rowLabel, { color: colors.textMuted }]}>
        {label}
      </Text>
      <Text style={[styles.rowValue, { color: colors.textMuted }]}>{note}</Text>
    </View>
  );
}

/**
 * A calorie or macro target row showing: effective value + unit, provenance
 * line ("└ from your goal + metrics" or "✎ set by you"), and a Reset button
 * when the target is overridden. The provenance marker carries a VoiceOver
 * label as required by the accessibility spec.
 */
function TargetRow({
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
  colors: ReturnType<typeof useTheme>['colors'];
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

function OverrideEditCard({
  label,
  value,
  onChangeText,
  saving,
  error,
  onSave,
  onCancel,
  colors,
  testID,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  saving: boolean;
  error?: string | null;
  onSave: () => void;
  onCancel: () => void;
  colors: ReturnType<typeof useTheme>['colors'];
  testID?: string;
}) {
  return (
    <EditCard colors={colors} testID={testID}>
      <Text style={[styles.editLabel, { color: colors.textSecondary }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChangeText}
        keyboardType="number-pad"
        inputMode="numeric"
        style={[
          styles.overrideInput,
          {
            backgroundColor: colors.surface,
            color: colors.text,
            borderColor: colors.separator,
          },
        ]}
      />
      {error && (
        <InlineError message={error} colors={colors} testID={`${testID}-error`} />
      )}
      <View style={styles.editActions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Cancel override"
          onPress={onCancel}
          style={[styles.editButton, { backgroundColor: colors.controlBackground }]}
        >
          <Text style={[styles.editButtonLabel, { color: colors.textSecondary }]}>
            Cancel
          </Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Save override"
          accessibilityState={{ disabled: saving }}
          disabled={saving}
          onPress={onSave}
          style={[
            styles.editButton,
            { backgroundColor: colors.accent, opacity: saving ? 0.5 : 1 },
          ]}
        >
          <Text style={[styles.editButtonLabel, { color: colors.accentForeground }]}>
            {saving ? 'Saving…' : 'Save'}
          </Text>
        </Pressable>
      </View>
    </EditCard>
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
  colors: ReturnType<typeof useTheme>['colors'];
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

function Segmented<T extends string>({
  options,
  selected,
  onSelect,
  accessibilityLabel,
  colors,
  compact = false,
}: {
  options: readonly { value: T; label: string }[];
  selected: T;
  onSelect: (v: T) => void;
  accessibilityLabel: string;
  colors: ReturnType<typeof useTheme>['colors'];
  compact?: boolean;
}) {
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={[
        styles.segmented,
        { backgroundColor: colors.controlBackground },
        compact && styles.segmentedCompact,
      ]}
    >
      {options.map((opt) => {
        const isSelected = opt.value === selected;
        return (
          <Pressable
            key={opt.value}
            accessibilityRole="radio"
            accessibilityState={{ selected: isSelected }}
            accessibilityLabel={opt.label}
            onPress={() => onSelect(opt.value)}
            style={[
              styles.segment,
              isSelected && { backgroundColor: colors.surfaceRaised },
            ]}
          >
            <Text
              style={[
                styles.segmentLabel,
                {
                  color: isSelected ? colors.text : colors.textSecondary,
                  fontWeight: isSelected ? '600' : '400',
                },
              ]}
            >
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

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
  sectionHeader: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginTop: spacing.xl,
    marginBottom: spacing.xs,
    marginLeft: spacing.xs,
  },
  groupedCard: {
    overflow: 'hidden',
    marginBottom: spacing.xs,
  },
  editCard: {
    padding: spacing.md,
    marginTop: spacing.xs,
    marginBottom: spacing.xs,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    marginLeft: spacing.base,
  },
  settingsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  comingSoonRow: {
    opacity: 0.72,
  },
  rowLabel: {
    fontSize: typeScale.body,
    flex: 1,
  },
  rowRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  rowValue: {
    fontSize: typeScale.subhead,
  },
  rowChevron: {
    fontSize: typeScale.body,
    fontWeight: '300',
  },
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
  noTargetRow: {
    padding: spacing.base,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  noTargetText: {
    fontSize: typeScale.subhead,
    textAlign: 'center',
  },
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
    flex: 1,
  },
  prefSubtitle: {
    fontSize: typeScale.footnote,
  },
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
  editLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  editActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
    justifyContent: 'flex-end',
  },
  editButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    minHeight: 36,
    minWidth: 70,
    alignItems: 'center',
    justifyContent: 'center',
  },
  editButtonLabel: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
  },
  overrideInput: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    fontSize: typeScale.body,
    minHeight: 44,
  },
  bodyEditInputs: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  bodyEditInput: {
    flex: 1,
  },
  inlineError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
  },
  formulaChoice: {
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  formulaChoiceLabel: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
  },
  formulaChoiceDesc: {
    fontSize: typeScale.footnote,
    marginTop: 2,
  },
  segmented: {
    flexDirection: 'row',
    borderRadius: radius.md,
    padding: 2,
    gap: 2,
  },
  segmentedCompact: {
    flexShrink: 1,
  },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    alignItems: 'center',
    minHeight: 36,
    justifyContent: 'center',
  },
  segmentLabel: {
    fontSize: typeScale.footnote,
  },
});
