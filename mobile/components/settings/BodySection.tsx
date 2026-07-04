/**
 * The BODY section (FTY-203, extracted from SettingsScreen).
 *
 * Weight, height, birth year, and the metabolic-formula ("Calculation
 * preference") rows, plus the inline editors for each. Units follow the profile
 * preference (kg/cm vs lb/ft+in); imperial height is captured as feet + inches
 * so the combined value is never silently dropped.
 */

import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { spacing, typeScale, radius } from '@/theme';
import {
  METABOLIC_FORMULA_OPTIONS,
  metersToFeetInches,
} from '@/state/profile';

import {
  EditCard,
  EditCardActions,
  EditFieldLabel,
  GroupedCard,
  InlineError,
  SectionHeader,
  Separator,
  DisclosureRow,
  fieldStyles,
  type SettingsColors,
} from './primitives';
import { settingsFormulaCopy } from './copy';
import type { SettingsController } from './useSettingsController';

export function BodySection({
  c,
  colors,
}: {
  c: SettingsController;
  colors: SettingsColors;
}) {
  const { profile, isMetric, formulaCopy } = c;

  return (
    <>
      <SectionHeader title="BODY" colors={colors} />
      <GroupedCard colors={colors}>
        <DisclosureRow
          label="Weight"
          value={
            profile?.weight_kg != null
              ? isMetric
                ? `${profile.weight_kg} kg`
                : `${Math.round(profile.weight_kg / 0.45359237)} lb`
              : '—'
          }
          onPress={() => c.openBodyEdit('weight')}
          colors={colors}
          accessibilityLabel={`Weight: ${profile?.weight_kg != null ? (isMetric ? `${profile.weight_kg} kilograms` : `${Math.round(profile.weight_kg / 0.45359237)} pounds`) : 'not set'}`}
          accessibilityHint="Double-tap to edit your weight"
        />
        <Separator colors={colors} />
        <DisclosureRow
          label="Height"
          value={
            profile?.height_m != null
              ? isMetric
                ? `${Math.round(profile.height_m * 100)} cm`
                : `${metersToFeetInches(profile.height_m).feet} ft ${metersToFeetInches(profile.height_m).inches} in`
              : '—'
          }
          onPress={() => c.openBodyEdit('height')}
          colors={colors}
          accessibilityLabel={`Height: ${profile?.height_m != null ? (isMetric ? `${Math.round(profile.height_m * 100)} centimetres` : `${metersToFeetInches(profile.height_m).feet} feet ${metersToFeetInches(profile.height_m).inches} inches`) : 'not set'}`}
          accessibilityHint="Double-tap to edit your height"
        />
        <Separator colors={colors} />
        <DisclosureRow
          label="Age"
          value={profile?.birth_year != null ? `Born ${profile.birth_year}` : '—'}
          onPress={() => c.openBodyEdit('birthYear')}
          colors={colors}
          accessibilityLabel={`Age: ${profile?.birth_year != null ? `birth year ${profile.birth_year}` : 'not set'}`}
          accessibilityHint="Double-tap to edit your birth year"
        />
        <Separator colors={colors} />
        <DisclosureRow
          label="Calculation preference"
          value={formulaCopy?.label ?? '—'}
          onPress={() => c.openBodyEdit('formula')}
          colors={colors}
          accessibilityLabel={`Calculation preference: ${formulaCopy?.label ?? 'not set'}${formulaCopy ? `. ${formulaCopy.description}` : ''}`}
          accessibilityHint="Double-tap to change your metabolic formula"
        />
      </GroupedCard>

      {/* Body metric inline edit */}
      {c.editingBodyMetric && c.editingBodyMetric !== 'formula' && (
        <EditCard colors={colors} testID="body-metric-edit-card">
          <EditFieldLabel colors={colors}>
            {c.editingBodyMetric === 'weight'
              ? `New weight (${isMetric ? 'kg' : 'lb'})`
              : c.editingBodyMetric === 'height'
                ? `New height (${isMetric ? 'cm' : 'ft + in'})`
                : 'Birth year'}
          </EditFieldLabel>
          <View style={styles.bodyEditInputs}>
            <TextInput
              accessibilityLabel={
                c.editingBodyMetric === 'weight'
                  ? `New weight in ${isMetric ? 'kilograms' : 'pounds'}`
                  : c.editingBodyMetric === 'height'
                    ? `New height in ${isMetric ? 'centimetres' : 'feet'}`
                    : 'New birth year'
              }
              value={c.bodyEditValue}
              onChangeText={c.setBodyEditValue}
              keyboardType="numeric"
              inputMode="numeric"
              style={[
                fieldStyles.numericInput,
                styles.bodyEditInput,
                {
                  backgroundColor: colors.surface,
                  color: colors.text,
                  borderColor: colors.separator,
                },
              ]}
            />
            {c.editingBodyMetric === 'height' && !isMetric && (
              <TextInput
                accessibilityLabel="New height inches"
                value={c.bodyEditInches}
                onChangeText={c.setBodyEditInches}
                keyboardType="numeric"
                inputMode="numeric"
                placeholder="in"
                placeholderTextColor={colors.textMuted}
                style={[
                  fieldStyles.numericInput,
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
          {c.actionError && (
            <InlineError message={c.actionError} colors={colors} testID="body-edit-error" />
          )}
          <EditCardActions
            colors={colors}
            saving={c.bodySaving}
            onCancel={c.cancelBodyEdit}
            cancelAccessibilityLabel="Cancel body metric edit"
            onSave={() => void c.handleSaveBodyMetric()}
            saveAccessibilityLabel="Save body metric"
          />
        </EditCard>
      )}

      {c.editingBodyMetric === 'formula' && (
        <EditCard colors={colors} testID="formula-edit-card">
          {METABOLIC_FORMULA_OPTIONS.map((opt) => {
            const selected = c.bodyEditFormula === opt.value;
            const copy = settingsFormulaCopy(opt.value);
            return (
              <Pressable
                key={opt.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${copy?.label ?? opt.label}. ${copy?.description ?? opt.description}`}
                onPress={() => c.setBodyEditFormula(opt.value)}
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
                    { color: selected ? colors.accentText : colors.text },
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
          {c.actionError && (
            <InlineError message={c.actionError} colors={colors} testID="formula-edit-error" />
          )}
          <EditCardActions
            colors={colors}
            saving={c.bodySaving}
            onCancel={c.cancelBodyEdit}
            cancelAccessibilityLabel="Cancel formula edit"
            onSave={() => void c.handleSaveBodyMetric()}
            saveAccessibilityLabel="Save calculation preference"
          />
        </EditCard>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  bodyEditInputs: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  bodyEditInput: {
    flex: 1,
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
});
