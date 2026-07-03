/**
 * The YOU section (FTY-203, extracted from SettingsScreen).
 *
 * Goal summary + inline goal editor, then the calorie/macro targets with their
 * provenance, override editors, and the mini target-reveal. Editing goal/pace
 * recomputes the plan and reveals the new targets in place.
 */

import { StyleSheet, Text, View } from 'react-native';

import { spacing, typeScale } from '@/theme';
import type { GoalDirection, PacePreset } from '@/api/goals';

import {
  EditCard,
  EditCardActions,
  EditFieldLabel,
  GroupedCard,
  InlineError,
  Segmented,
  SectionHeader,
  Separator,
  DisclosureRow,
  type SettingsColors,
} from './primitives';
import { TargetRow } from './TargetRow';
import { OverrideEditCard } from './OverrideEditCard';
import { MiniTargetReveal } from './MiniTargetReveal';
import type { SettingsController } from './useSettingsController';

export function YouSection({
  c,
  colors,
}: {
  c: SettingsController;
  colors: SettingsColors;
}) {
  const { target, noTarget } = c;

  return (
    <>
      <SectionHeader title="YOU" colors={colors} />

      {/* Goal row */}
      <GroupedCard colors={colors}>
        <DisclosureRow
          label="Goal"
          value={c.goalDetail}
          onPress={c.openGoalEdit}
          accessibilityLabel={`Goal: ${c.goalDetail}`}
          accessibilityHint="Double-tap to edit your goal"
          colors={colors}
        />
      </GroupedCard>

      {/* Goal edit inline */}
      {c.editingGoal && (
        <EditCard colors={colors} testID="goal-edit-card">
          <EditFieldLabel colors={colors}>Direction</EditFieldLabel>
          <Segmented<GoalDirection>
            options={[
              { value: 'loss', label: 'Lose' },
              { value: 'maintain', label: 'Maintain' },
              { value: 'gain', label: 'Gain' },
            ]}
            selected={c.editDirection}
            onSelect={c.handleDirectionChange}
            accessibilityLabel="Goal direction"
            colors={colors}
          />
          {c.editDirection !== 'maintain' && (
            <>
              <EditFieldLabel colors={colors} style={{ marginTop: spacing.sm }}>
                Pace
              </EditFieldLabel>
              <Segmented<PacePreset>
                options={[
                  { value: 'gentle', label: 'Gentle' },
                  { value: 'steady', label: 'Steady' },
                  ...(c.editDirection === 'loss'
                    ? [{ value: 'faster' as PacePreset, label: 'Faster' }]
                    : []),
                ]}
                selected={c.editPace}
                onSelect={c.setEditPace}
                accessibilityLabel="Goal pace"
                colors={colors}
              />
            </>
          )}
          {c.actionError && (
            <InlineError message={c.actionError} colors={colors} testID="goal-edit-error" />
          )}
          <EditCardActions
            colors={colors}
            saving={c.goalSaving}
            onCancel={c.cancelGoalEdit}
            cancelAccessibilityLabel="Cancel goal edit"
            onSave={() => void c.handleSaveGoal()}
            saveAccessibilityLabel="Save goal"
          />
        </EditCard>
      )}

      {/* Calorie + macro targets */}
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
              onOverride={c.openCalorieOverride}
              onReset={() => void c.handleReset(['calories'])}
              colors={colors}
              testID="calorie-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Protein"
              unit="g"
              component={target.protein_g}
              onOverride={() => c.openMacroOverride('protein_g')}
              onReset={() => void c.handleReset(['protein'])}
              colors={colors}
              testID="protein-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Carbs"
              unit="g"
              component={target.carbs_g}
              onOverride={() => c.openMacroOverride('carbs_g')}
              onReset={() => void c.handleReset(['carbs'])}
              colors={colors}
              testID="carbs-target-row"
            />
            <Separator colors={colors} />
            <TargetRow
              label="Fat"
              unit="g"
              component={target.fat_g}
              onOverride={() => c.openMacroOverride('fat_g')}
              onReset={() => void c.handleReset(['fat'])}
              colors={colors}
              testID="fat-target-row"
            />
          </>
        )}
      </GroupedCard>

      {/* Action error not tied to an open editor (e.g. a failed reset) */}
      {c.hasStandaloneActionError && c.actionError && (
        <InlineError
          message={c.actionError}
          colors={colors}
          testID="target-action-error"
          style={{ marginTop: spacing.xs }}
        />
      )}

      {/* Calorie override edit */}
      {c.editingCalorieOverride && (
        <OverrideEditCard
          label="Override calorie target (kcal)"
          value={c.overrideValue}
          onChangeText={c.setOverrideValue}
          saving={c.overrideSaving}
          error={c.actionError}
          onSave={() => void c.handleSaveOverride()}
          onCancel={c.cancelCalorieOverride}
          colors={colors}
          testID="calorie-override-edit"
        />
      )}

      {/* Macro override edit */}
      {c.editingMacroOverride && (
        <OverrideEditCard
          label={`Override ${c.editingMacroOverride.replace('_g', '')} target (g)`}
          value={c.overrideValue}
          onChangeText={c.setOverrideValue}
          saving={c.overrideSaving}
          error={c.actionError}
          onSave={() => void c.handleSaveOverride()}
          onCancel={c.cancelMacroOverride}
          colors={colors}
          testID="macro-override-edit"
        />
      )}

      {/* Mini target-reveal */}
      {c.revealTarget && (
        <MiniTargetReveal
          target={c.revealTarget}
          clamped={c.revealClamped}
          opacity={c.revealOpacity}
          colors={colors}
        />
      )}
    </>
  );
}

const styles = StyleSheet.create({
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
});
