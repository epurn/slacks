/**
 * Settings screen controller (FTY-203, extracted from SettingsScreen).
 *
 * Owns the whole non-visual lifecycle of the Profile / Settings screen: the
 * initial load of profile + target + active goal + on-device preferences, all
 * edit state (goal, body metrics, calorie/macro overrides), the save/reset
 * round-trips, the mini target-reveal animation, and the derived display values
 * the sections render. The screen shell wires the returned state to the focused
 * section components; the sections stay presentational.
 *
 * Privacy: sensitive figures (targets, macros, body metrics) are never written
 * to logs or error messages — errors carry only status-derived, non-sensitive
 * copy (see `actionErrorMessage`).
 */

import { useCallback, useEffect, useState } from 'react';
import { AccessibilityInfo, Animated } from 'react-native';

import {
  getTarget,
  createGoal,
  getActiveGoal,
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
import type { ProfileDTO } from '@/api/profile';
import type { TargetReadModel } from '@/api/dailySummary';
import { useGoalDirectionController } from '@/state/goalDirection';
import {
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
  cmToMeters,
  feetInchesToMeters,
  kilograms,
  poundsToKilograms,
  type MetabolicFormula,
  type UnitsPreference,
} from '@/state/profile';
import type { Session } from '@/state/session';
import { toApiSession, useSession, useSessionController } from '@/state/session';
import type { ColorSchemeOverride } from '@/theme';

import { settingsFormulaCopy } from './copy';
import { goalSummaryDetail } from '../settingsGoalSummary';

export type BodyMetric = 'weight' | 'height' | 'birthYear' | 'formula';
export type MacroOverrideKey = 'protein_g' | 'carbs_g' | 'fat_g';

export interface SettingsControllerProps {
  /** Injectable session for tests. When omitted, the live session is used. */
  session?: Session;
  /** Injectable API functions for testing. */
  getTargetFn?: typeof getTarget;
  getProfileFn?: typeof getProfile;
  putProfileFn?: typeof putProfile;
  createGoalFn?: typeof createGoal;
  getActiveGoalFn?: typeof getActiveGoal;
  setTargetOverrideFn?: typeof setTargetOverride;
  resetTargetOverrideFn?: typeof resetTargetOverride;
  /** Injectable on-device settings stores. */
  settingsStore?: AppSettingsStore;
  cadenceStore?: CadenceStore;
  notificationsAdapter?: NotificationsAdapter;
  /**
   * Callback invoked when the user changes the appearance preference so the
   * root ThemeProvider can be updated. Injectable for tests.
   */
  onAppearanceChange?: (v: ColorSchemeOverride) => void;
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

export function useSettingsController({
  session: sessionOverride,
  getTargetFn = getTarget,
  getProfileFn = getProfile,
  putProfileFn = putProfile,
  createGoalFn = createGoal,
  getActiveGoalFn = getActiveGoal,
  setTargetOverrideFn = setTargetOverride,
  resetTargetOverrideFn = resetTargetOverride,
  settingsStore = fileAppSettingsStore,
  cadenceStore = fileCadenceStore,
  notificationsAdapter = expoNotificationsAdapter,
  onAppearanceChange,
}: SettingsControllerProps) {
  const liveSession = useSession();
  const sessionController = useSessionController();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const {
    goalDirection: sessionGoalDirection,
    setGoalDirection: setKnownGoalDirection,
  } = useGoalDirectionController();

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

  const [editingBodyMetric, setEditingBodyMetric] = useState<BodyMetric | null>(
    null,
  );
  const [bodyEditValue, setBodyEditValue] = useState('');
  // Imperial height is captured as feet (bodyEditValue) + inches (this) so the
  // editor matches the "ft + in" display and never silently drops the inches.
  const [bodyEditInches, setBodyEditInches] = useState('');
  const [bodyEditFormula, setBodyEditFormula] = useState<MetabolicFormula | null>(null);
  const [bodySaving, setBodySaving] = useState(false);

  const [editingCalorieOverride, setEditingCalorieOverride] = useState(false);
  const [editingMacroOverride, setEditingMacroOverride] =
    useState<MacroOverrideKey | null>(null);
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
      // The returning user's active goal (direction + pace, both recovered
      // server-side from the persisted trajectory) so the collapsed Goal row
      // summarises the real goal — direction + pace — on a cold load instead of
      // depending on an in-session edit. A load failure degrades to the in-memory
      // cross-screen direction rather than blocking settings.
      getActiveGoalFn(apiSession).catch(() => null),
      settingsStore.getAppearance(),
      cadenceStore.getCadence(),
    ])
      .then(([prof, tgt, goal, app, cad]) => {
        if (!active) return;
        setProfile(prof);
        if (tgt === null) {
          setNoTarget(true);
        } else {
          setTarget(tgt);
        }
        if (goal !== null) {
          setGoalDirection(goal.direction);
          setGoalPace(goal.pace);
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
  }, [
    session,
    getProfileFn,
    getTargetFn,
    getActiveGoalFn,
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
  // Pace is recovered from the real goal on a cold load (`GET /goal` returns the
  // direction + the pace preset, both recovered server-side from the persisted
  // trajectory) and refreshed from the user's own edit this session — never
  // inferred client-side from target numbers or replayed from a local cache. It
  // is `null` only for a maintain goal (no pace) or a legacy goal off the band
  // grid, in which case the row summarises the real goal by its direction alone.
  const currentGoalPace = goalPace;

  const openGoalEdit = useCallback(() => {
    setActionError(null);
    setEditDirection(currentGoalDirection ?? 'loss');
    setEditPace(currentGoalPace ?? 'steady');
    setEditingGoal(true);
  }, [currentGoalDirection, currentGoalPace]);

  const cancelGoalEdit = useCallback(() => {
    setActionError(null);
    setEditingGoal(false);
  }, []);

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
      // Reflect the pace the user just chose in the collapsed row immediately.
      // It is not cached on-device: the goal round-tripped to the server (the
      // authoritative store), so a later cold launch recovers the pace from
      // `GET /goal` rather than from a stale local copy.
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
    (metric: BodyMetric) => {
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

  const cancelBodyEdit = useCallback(() => {
    setActionError(null);
    setEditingBodyMetric(null);
  }, []);

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

  const openCalorieOverride = useCallback(() => {
    if (!target) return;
    setActionError(null);
    setEditingCalorieOverride(true);
    setOverrideValue(String(target.calories.effective));
  }, [target]);

  const openMacroOverride = useCallback(
    (macro: MacroOverrideKey) => {
      if (!target) return;
      setActionError(null);
      setEditingMacroOverride(macro);
      setOverrideValue(String(target[macro].effective));
    },
    [target],
  );

  const cancelCalorieOverride = useCallback(() => {
    setActionError(null);
    setEditingCalorieOverride(false);
  }, []);

  const cancelMacroOverride = useCallback(() => {
    setActionError(null);
    setEditingMacroOverride(null);
  }, []);

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

  // ── Derived display values ────────────────────────────────────────────────

  const isMetric = profile?.units_preference === 'metric';
  const goalIsActive = !noTarget && target !== null;
  const goalDetail = goalIsActive
    ? goalSummaryDetail(currentGoalDirection, currentGoalPace)
    : 'Not set';
  const formulaCopy = settingsFormulaCopy(profile?.metabolic_formula);

  // A save/reset error not tied to an open editor (e.g. a failed reset) surfaces
  // near the targets rather than inside a card.
  const hasStandaloneActionError =
    actionError !== null &&
    !editingGoal &&
    !editingBodyMetric &&
    !editingCalorieOverride &&
    !editingMacroOverride;

  return {
    // status
    session,
    loading,
    loadError,
    // profile / target
    profile,
    target,
    noTarget,
    isMetric,
    formulaCopy,
    // goal
    goalDetail,
    openGoalEdit,
    cancelGoalEdit,
    editingGoal,
    editDirection,
    editPace,
    handleDirectionChange,
    setEditPace,
    goalSaving,
    handleSaveGoal,
    // targets / overrides
    handleReset,
    openCalorieOverride,
    openMacroOverride,
    editingCalorieOverride,
    editingMacroOverride,
    overrideValue,
    setOverrideValue,
    overrideSaving,
    handleSaveOverride,
    cancelCalorieOverride,
    cancelMacroOverride,
    // body
    editingBodyMetric,
    openBodyEdit,
    cancelBodyEdit,
    bodyEditValue,
    setBodyEditValue,
    bodyEditInches,
    setBodyEditInches,
    bodyEditFormula,
    setBodyEditFormula,
    bodySaving,
    handleSaveBodyMetric,
    // reveal
    revealTarget,
    revealClamped,
    revealOpacity,
    // preferences
    appearance,
    cadence,
    handleAppearanceChange,
    handleCadenceChange,
    handleUnitsChange,
    // account
    handleSignOut,
    // shared feedback
    actionError,
    hasStandaloneActionError,
  };
}

export type SettingsController = ReturnType<typeof useSettingsController>;
