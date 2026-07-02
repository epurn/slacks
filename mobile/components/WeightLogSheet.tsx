/**
 * Weight log sheet for FTY-101. A bottom-sheet-style modal for logging a
 * body-weight entry from the Trends screen.
 *
 * Defaults to today's date and seeds the input with the user's last logged
 * weight (in display units). Converts to canonical kg at the API boundary
 * per the FTY-070 contract. After a successful save, calls onSaved so the
 * parent can re-fetch and reschedule the reminder.
 *
 * Privacy: weight values are never emitted to logs or error messages.
 */

import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useCallback, useState } from "react";

import {
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import { WeightEntryInput } from "@/components/WeightEntryInput";
import type { UnitsPreference } from "@/state/profile";
import { formatHumanDate, kgToDisplay } from "@/state/weightEntries";
import type { ApiSession } from "@/state/session";
import { useTheme, spacing, typeScale, radius } from "@/theme";

interface WeightLogSheetProps {
  visible: boolean;
  onClose: () => void;
  /** Called after a successful weight save. */
  onSaved: (date: string) => void;
  session: ApiSession;
  unitsPreference: UnitsPreference;
  /** The most recent weight entry, used to seed the input. */
  lastEntry: WeightEntryDTO | null;
  /** Today's date string (YYYY-MM-DD), injectable for tests. */
  today: string;
  create?: typeof createWeightEntryApi;
}

function messageFor(error: unknown): string {
  return error instanceof WeightApiError
    ? error.message
    : "Something went wrong. Please try again.";
}

export function WeightLogSheet({
  visible,
  onClose,
  onSaved,
  session,
  unitsPreference,
  lastEntry,
  today,
  create = createWeightEntryApi,
}: WeightLogSheetProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const seedValue =
    lastEntry != null ? kgToDisplay(lastEntry.weight_kg, unitsPreference) : undefined;

  const handleSubmit = useCallback(
    async (weight: number) => {
      if (submitting) return;
      setSubmitting(true);
      setSubmitError(null);
      try {
        await create(session, weight, today);
        onSaved(today);
        onClose();
      } catch (error) {
        setSubmitError(messageFor(error));
      } finally {
        setSubmitting(false);
      }
    },
    [submitting, create, session, today, onSaved, onClose],
  );

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="formSheet"
      onRequestClose={onClose}
    >
      <View
        testID="weight-log-sheet"
        style={[
          styles.container,
          {
            backgroundColor: colors.surface,
            paddingTop: insets.top + spacing.base,
            paddingBottom: insets.bottom + spacing.xl,
          },
        ]}
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={[styles.title, { color: colors.text }]}>
            Log weight
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            onPress={onClose}
            style={styles.closeBtn}
          >
            <Text style={[styles.closeBtnLabel, { color: colors.accent }]}>
              Cancel
            </Text>
          </Pressable>
        </View>

        <Text style={[styles.dateLabel, { color: colors.textSecondary }]}>
          {formatHumanDate(today, today)}
        </Text>

        <View
          style={[
            styles.inputCard,
            { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
          ]}
        >
          <WeightEntryInput
            unitsPreference={unitsPreference}
            submitting={submitting}
            submitError={submitError}
            initialValue={seedValue}
            onSubmit={(w) => void handleSubmit(w)}
          />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: spacing.base,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.sm,
  },
  title: {
    fontSize: typeScale.title2,
    fontWeight: "700",
  },
  closeBtn: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  closeBtnLabel: {
    fontSize: typeScale.body,
    fontWeight: "500",
  },
  dateLabel: {
    fontSize: typeScale.subhead,
    marginBottom: spacing.base,
  },
  inputCard: {
    padding: spacing.base,
  },
});
