/**
 * Shared Settings primitives — the small, native building blocks the Settings
 * sections compose from (grouped cards, disclosure rows, inline edit chrome, the
 * segmented control). Extracted from the former monolithic SettingsScreen so
 * each section file stays focused on its own product responsibility (FTY-203).
 */

import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useTheme, spacing, typeScale, radius } from '@/theme';

/** The resolved theme palette threaded through every Settings component. */
export type SettingsColors = ReturnType<typeof useTheme>['colors'];

export function SectionHeader({
  title,
  colors,
}: {
  title: string;
  colors: SettingsColors;
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

export function GroupedCard({
  children,
  colors,
  style,
}: {
  children: ReactNode;
  colors: SettingsColors;
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

export function EditCard({
  children,
  colors,
  testID,
}: {
  children: ReactNode;
  colors: SettingsColors;
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

/** The uppercase field caption above an inline editor's input/controls. */
export function EditFieldLabel({
  children,
  colors,
  style,
}: {
  children: ReactNode;
  colors: SettingsColors;
  style?: object;
}) {
  return (
    <Text style={[styles.editLabel, { color: colors.textSecondary }, style]}>
      {children}
    </Text>
  );
}

/** The shared Cancel / Save action pair at the foot of every inline edit card. */
export function EditCardActions({
  colors,
  saving,
  onCancel,
  cancelAccessibilityLabel,
  onSave,
  saveAccessibilityLabel,
}: {
  colors: SettingsColors;
  saving: boolean;
  onCancel: () => void;
  cancelAccessibilityLabel: string;
  onSave: () => void;
  saveAccessibilityLabel: string;
}) {
  return (
    <View style={styles.editActions}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={cancelAccessibilityLabel}
        onPress={onCancel}
        style={[styles.editButton, { backgroundColor: colors.controlBackground }]}
      >
        <Text style={[styles.editButtonLabel, { color: colors.textSecondary }]}>
          Cancel
        </Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={saveAccessibilityLabel}
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
  );
}

export function Separator({ colors }: { colors: SettingsColors }) {
  return (
    <View style={[styles.separator, { backgroundColor: colors.separator }]} />
  );
}

/** A calm, in-place error line for a failed save/reset (no sensitive context). */
export function InlineError({
  message,
  colors,
  testID,
  style,
}: {
  message: string;
  colors: SettingsColors;
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

/**
 * A tappable label/value disclosure row (chevron trailing) — the shared shape of
 * the Goal row and every editable BODY metric row. The optional hint keeps the
 * VoiceOver copy each caller already ships.
 */
export function DisclosureRow({
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
  colors: SettingsColors;
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

/**
 * A muted, non-tappable row whose trailing note (e.g. "Coming soon") stands in
 * for a not-yet-wired flow. Deliberately carries no role/hint/onPress so it never
 * looks like an inert-but-tappable dead-end.
 */
export function ComingSoonDisclosureRow({
  label,
  accessibilityLabel,
  colors,
  note,
}: {
  label: string;
  accessibilityLabel: string;
  colors: SettingsColors;
  /** Trailing status text (e.g. "Coming soon") for a not-yet-wired row. */
  note: string;
}) {
  return (
    <View
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ disabled: true }}
      style={[styles.settingsRow, styles.comingSoonRow]}
    >
      <Text style={[styles.rowLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.rowValue, { color: colors.textMuted }]}>{note}</Text>
    </View>
  );
}

export function Segmented<T extends string>({
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
  colors: SettingsColors;
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

/** The numeric TextInput style shared by the override and body-metric editors. */
export const fieldStyles = StyleSheet.create({
  numericInput: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    fontSize: typeScale.body,
    minHeight: 44,
  },
});

const styles = StyleSheet.create({
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
  inlineError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
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
