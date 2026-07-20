/**
 * Shared native menu/picker (FTY-403).
 *
 * A typed value/label control that shows the current choice inline and reveals
 * the full option list on tap — the native iOS "pop-up button" pattern. It is
 * the right control when a list has more labelled discrete choices than a
 * segmented control can hold at equal width (the weigh-in cadence grew to seven
 * options, which no longer fit the `UISegmentedControl` without truncation —
 * FTY-347), and where a slider would be wrong for named choices.
 *
 * Per *Native skeleton, bespoke soul*: this is the platform menu, never a
 * hand-rolled pill/radio group. On iOS it presents the system
 * `ActionSheetIOS` — the same native chooser the Today composer already uses —
 * so the option list, light/dark appearance, VoiceOver semantics, and dismissal
 * are all owned by UIKit and free of truncation. Off iOS (Android, and the Jest
 * android/E2E path) `ActionSheetIOS` does not exist, so the same option list is
 * presented in an accessible bottom-anchored `Modal` sheet, keeping the control
 * fully functional and reachable on every platform.
 *
 * The API mirrors `SegmentedControl`: callers speak their own domain enum —
 * value in, selection out — while the control owns presentation.
 */

import { useCallback, useState } from 'react';
import {
  ActionSheetIOS,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { useTheme, spacing, typeScale, radius } from '@/theme';

import { AppIcon } from './AppIcon';

export interface MenuPickerOption<T extends string> {
  readonly value: T;
  readonly label: string;
}

export function MenuPicker<T extends string>({
  options,
  selected,
  onSelect,
  accessibilityLabel,
  title,
  testID,
}: {
  options: readonly MenuPickerOption<T>[];
  selected: T;
  onSelect: (value: T) => void;
  /** VoiceOver label for the trigger (e.g. "Weigh-in cadence"). */
  accessibilityLabel: string;
  /** Optional heading shown above the option list. */
  title?: string;
  testID?: string;
}) {
  const { colors } = useTheme();
  const [fallbackOpen, setFallbackOpen] = useState(false);

  const selectedOption =
    options.find((o) => o.value === selected) ?? options[0];
  const selectedLabel = selectedOption?.label ?? '';

  const open = useCallback(() => {
    if (Platform.OS === 'ios') {
      const labels = options.map((o) => o.label);
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: [...labels, 'Cancel'],
          cancelButtonIndex: labels.length,
          title,
        },
        (index) => {
          const picked = options[index];
          if (picked) onSelect(picked.value);
        },
      );
      return;
    }
    setFallbackOpen(true);
  }, [options, onSelect, title]);

  const pickFromFallback = useCallback(
    (value: T) => {
      setFallbackOpen(false);
      onSelect(value);
    },
    [onSelect],
  );

  return (
    <>
      <Pressable
        testID={testID}
        accessibilityRole="button"
        accessibilityLabel={`${accessibilityLabel}, ${selectedLabel}`}
        accessibilityHint="Opens the list of options"
        onPress={open}
        style={styles.trigger}
      >
        <Text style={[styles.triggerValue, { color: colors.accentText }]}>
          {selectedLabel}
        </Text>
        <AppIcon
          name="chevron.up.chevron.down"
          size={typeScale.footnote}
          color={colors.accentText}
        />
      </Pressable>

      {/* Non-iOS fallback: the same options in an accessible bottom sheet. */}
      <Modal
        visible={fallbackOpen}
        transparent
        animationType="fade"
        presentationStyle="overFullScreen"
        onRequestClose={() => setFallbackOpen(false)}
        accessibilityViewIsModal
      >
        <View style={styles.fallbackOverlay}>
          <Pressable
            style={StyleSheet.absoluteFill}
            accessibilityLabel="Close menu"
            accessibilityRole="button"
            onPress={() => setFallbackOpen(false)}
          />
          <View
            accessibilityViewIsModal
            accessibilityLabel={accessibilityLabel}
            style={[
              styles.fallbackSheet,
              { backgroundColor: colors.surfaceRaised },
            ]}
          >
            {title ? (
              <Text style={[styles.fallbackTitle, { color: colors.textMuted }]}>
                {title}
              </Text>
            ) : null}
            <ScrollView>
              {options.map((o) => {
                const isSelected = o.value === selected;
                return (
                  <Pressable
                    key={o.value}
                    accessibilityRole="button"
                    accessibilityState={{ selected: isSelected }}
                    accessibilityLabel={o.label}
                    onPress={() => pickFromFallback(o.value)}
                    style={styles.fallbackRow}
                  >
                    <Text
                      style={[
                        styles.fallbackRowLabel,
                        {
                          color: isSelected ? colors.accentText : colors.text,
                          fontWeight: isSelected ? '600' : '400',
                        },
                      ]}
                    >
                      {o.label}
                    </Text>
                    {isSelected ? (
                      <AppIcon
                        name="checkmark"
                        size={typeScale.body}
                        color={colors.accentText}
                      />
                    ) : null}
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    minHeight: 44,
    paddingVertical: spacing.xs,
    paddingLeft: spacing.sm,
  },
  triggerValue: {
    fontSize: typeScale.body,
    fontWeight: '600',
  },
  fallbackOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  fallbackSheet: {
    maxHeight: '70%',
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingVertical: spacing.sm,
  },
  fallbackTitle: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.sm,
  },
  fallbackRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  fallbackRowLabel: {
    fontSize: typeScale.body,
  },
});
