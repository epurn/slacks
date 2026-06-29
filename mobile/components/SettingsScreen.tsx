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

import {
  getTarget,
  createGoal,
  setTargetOverride,
  resetTargetOverride,
  type GoalDirection,
  type GoalTargetRequest,
  type GoalTargetResponse,
  type OverridableTargetKey,
  type PacePreset,
  type TargetOverridePayload,
} from '@/api/goals';
import { getProfile, putProfile } from '@/api/profile';
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

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

const PACE_LABELS: Record<PacePreset, string> = {
  gentle: 'Gentle',
  steady: 'Steady',
  faster: 'Faster',
};

const DIRECTION_LABELS: Record<GoalDirection, string> = {
  loss: 'Lose weight',
  maintain: 'Maintain weight',
  gain: 'Gain weight',
};

const APPEARANCE_OPTIONS: readonly { value: ColorSchemeOverride; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

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
  const [bodyEditFormula, setBodyEditFormula] = useState<MetabolicFormula | null>(null);
  const [bodySaving, setBodySaving] = useState(false);

  const [editingCalorieOverride, setEditingCalorieOverride] = useState(false);
  const [editingMacroOverride, setEditingMacroOverride] = useState<
    'protein_g' | 'carbs_g' | 'fat_g' | null
  >(null);
  const [overrideValue, setOverrideValue] = useState('');
  const [overrideSaving, setOverrideSaving] = useState(false);

  // Mini target-reveal
  const [revealTarget, setRevealTarget] = useState<TargetReadModel | null>(null);
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
      settingsStore.getAppearance(),
      cadenceStore.getCadence(),
    ])
      .then(([prof, tgt, app, cad]) => {
        if (!active) return;
        setProfile(prof);
        if (tgt === null) {
          setNoTarget(true);
        } else {
          setTarget(tgt);
        }
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
  }, [session, getProfileFn, getTargetFn, settingsStore, cadenceStore]);

  // ── Mini reveal animation ─────────────────────────────────────────────────

  const showReveal = useCallback(
    (tgt: TargetReadModel) => {
      setRevealTarget(tgt);
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

  const openGoalEdit = useCallback(() => {
    setEditDirection(goalDirection ?? 'loss');
    setEditPace(goalPace ?? 'steady');
    setEditingGoal(true);
  }, [goalDirection, goalPace]);

  const handleSaveGoal = useCallback(async () => {
    if (!session) return;
    setGoalSaving(true);
    const apiSession = toApiSession(session);
    const payload: GoalTargetRequest = {
      direction: editDirection,
      ...(editDirection !== 'maintain' ? { pace: editPace } : {}),
    };
    try {
      const reveal: GoalTargetResponse = await createGoalFn(apiSession, payload);
      setGoalDirection(reveal.target.direction);
      setGoalPace(editDirection !== 'maintain' ? editPace : null);
      setEditingGoal(false);
      // Fetch the full read-model (reveal only has calories, not macros)
      const updatedTarget = await getTargetFn(apiSession);
      setTarget(updatedTarget);
      setNoTarget(false);
      showReveal(updatedTarget);
    } catch {
      // Error is not logged (would expose sensitive context)
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
  ]);

  // ── Body metric edit handlers ─────────────────────────────────────────────

  const openBodyEdit = useCallback(
    (metric: 'weight' | 'height' | 'birthYear' | 'formula') => {
      setEditingBodyMetric(metric);
      setBodyEditValue('');
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
        if (!isFinite(raw)) throw new Error('invalid');
        updates.weight_kg = isMetric ? kilograms(raw) : poundsToKilograms(raw);
      } else if (editingBodyMetric === 'height') {
        const raw = parseFloat(bodyEditValue);
        if (!isFinite(raw)) throw new Error('invalid');
        updates.height_m = isMetric ? cmToMeters(raw) : feetInchesToMeters(raw, 0);
      } else if (editingBodyMetric === 'birthYear') {
        const year = parseInt(bodyEditValue, 10);
        if (!isFinite(year)) throw new Error('invalid');
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
    } catch {
      // Error not logged to avoid sensitive context
      setEditingBodyMetric(null);
    } finally {
      setBodySaving(false);
    }
  }, [
    session,
    profile,
    editingBodyMetric,
    bodyEditValue,
    bodyEditFormula,
    putProfileFn,
    getTargetFn,
    showReveal,
  ]);

  // ── Target override / reset handlers ─────────────────────────────────────

  const handleSaveOverride = useCallback(async () => {
    if (!session) return;
    setOverrideSaving(true);
    const apiSession = toApiSession(session);
    const val = parseInt(overrideValue, 10);
    if (!isFinite(val)) {
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
    } catch {
      // Error not logged
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
      const apiSession = toApiSession(session);
      try {
        const updatedTarget = await resetTargetOverrideFn(apiSession, targets);
        setTarget(updatedTarget);
      } catch {
        // Error not logged
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
      contentContainerStyle={{
        paddingTop: insets.top + 16,
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
          value={
            goalDirection
              ? `${DIRECTION_LABELS[goalDirection]}${goalPace && goalDirection !== 'maintain' ? ` · ${PACE_LABELS[goalPace]}` : ''}`
              : 'Not set'
          }
          onPress={openGoalEdit}
          accessibilityLabel={`Goal: ${
            goalDirection
              ? `${DIRECTION_LABELS[goalDirection]}${goalPace && goalDirection !== 'maintain' ? `, ${PACE_LABELS[goalPace]}` : ''}`
              : 'Not set'
          }`}
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
            onSelect={setEditDirection}
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
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel goal edit"
              onPress={() => setEditingGoal(false)}
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

      {/* Calorie override edit */}
      {editingCalorieOverride && (
        <OverrideEditCard
          label="Override calorie target (kcal)"
          value={overrideValue}
          onChangeText={setOverrideValue}
          saving={overrideSaving}
          onSave={() => void handleSaveOverride()}
          onCancel={() => setEditingCalorieOverride(false)}
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
          onSave={() => void handleSaveOverride()}
          onCancel={() => setEditingMacroOverride(null)}
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
          accessibilityLabel={`Updated targets: ${revealTarget.calories.effective} kcal calories, ${revealTarget.protein_g.effective} g protein, ${revealTarget.carbs_g.effective} g carbs, ${revealTarget.fat_g.effective} g fat`}
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
              clamped={revealTarget.calories.source === 'derived' && false}
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
                : `${Math.floor(profile.height_m * 39.37 / 12)} ft ${Math.round(profile.height_m * 39.37 % 12)} in`
              : '—'
          }
          onPress={() => openBodyEdit('height')}
          colors={colors}
          accessibilityLabel={`Height: ${profile?.height_m != null ? (isMetric ? `${Math.round(profile.height_m * 100)} centimetres` : `${Math.floor(profile.height_m * 39.37 / 12)} feet ${Math.round(profile.height_m * 39.37 % 12)} inches`) : 'not set'}`}
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
          value={
            METABOLIC_FORMULA_OPTIONS.find(
              (o) => o.value === profile?.metabolic_formula,
            )?.label ?? '—'
          }
          onPress={() => openBodyEdit('formula')}
          colors={colors}
          accessibilityLabel={`Calculation preference: ${METABOLIC_FORMULA_OPTIONS.find((o) => o.value === profile?.metabolic_formula)?.label ?? 'not set'}`}
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
                ? `New height (${isMetric ? 'cm' : 'ft'})`
                : 'Birth year'}
          </Text>
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
              {
                backgroundColor: colors.surface,
                color: colors.text,
                borderColor: colors.separator,
              },
            ]}
          />
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel body metric edit"
              onPress={() => setEditingBodyMetric(null)}
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
            return (
              <Pressable
                key={opt.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${opt.label}. ${opt.description}`}
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
                  {opt.label}
                </Text>
                <Text style={[styles.formulaChoiceDesc, { color: colors.textMuted }]}>
                  {opt.description}
                </Text>
              </Pressable>
            );
          })}
          <View style={styles.editActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Cancel formula edit"
              onPress={() => setEditingBodyMetric(null)}
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
        <DisclosureRow
          label="Export data"
          onPress={() => {}}
          accessibilityLabel="Export data"
          accessibilityHint="Opens data export flow"
          colors={colors}
        />
        <Separator colors={colors} />
        <DisclosureRow
          label="Delete account"
          onPress={() => {}}
          accessibilityLabel="Delete account"
          accessibilityHint="Opens account deletion flow"
          colors={colors}
          destructive
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

function DisclosureRow({
  label,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  colors,
  destructive = false,
}: {
  label: string;
  onPress: () => void;
  accessibilityLabel: string;
  accessibilityHint?: string;
  colors: ReturnType<typeof useTheme>['colors'];
  destructive?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      style={styles.settingsRow}
    >
      <Text
        style={[
          styles.rowLabel,
          { color: destructive ? colors.coral : colors.text },
        ]}
      >
        {label}
      </Text>
      <Text style={[styles.rowChevron, { color: colors.textMuted }]}>›</Text>
    </Pressable>
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
  onSave,
  onCancel,
  colors,
  testID,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  saving: boolean;
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
  colors,
}: {
  label: string;
  value: number;
  unit: string;
  clamped: boolean;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <View style={styles.revealItem}>
      <Text style={[styles.revealValue, { color: colors.text }]}>
        {`${value}`}
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
