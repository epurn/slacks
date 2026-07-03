/**
 * Inline calorie / macro override editor (FTY-203, extracted from SettingsScreen).
 *
 * A numeric field plus the shared Cancel / Save chrome; a failed save keeps the
 * card open and explains in place (`error`) rather than closing silently.
 */

import { TextInput } from 'react-native';

import {
  EditCard,
  EditCardActions,
  EditFieldLabel,
  InlineError,
  fieldStyles,
  type SettingsColors,
} from './primitives';

export function OverrideEditCard({
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
  colors: SettingsColors;
  testID?: string;
}) {
  return (
    <EditCard colors={colors} testID={testID}>
      <EditFieldLabel colors={colors}>{label}</EditFieldLabel>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChangeText}
        keyboardType="number-pad"
        inputMode="numeric"
        style={[
          fieldStyles.numericInput,
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
      <EditCardActions
        colors={colors}
        saving={saving}
        onCancel={onCancel}
        cancelAccessibilityLabel="Cancel override"
        onSave={onSave}
        saveAccessibilityLabel="Save override"
      />
    </EditCard>
  );
}
