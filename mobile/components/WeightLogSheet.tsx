/**
 * Weight log sheet for FTY-101. A true small (fit-to-content) native sheet for
 * logging a body-weight entry from the Trends screen (FTY-183).
 *
 * Defaults to today's date and seeds the input with the user's last logged
 * weight (in display units). Converts to canonical kg at the API boundary
 * per the FTY-070 contract. After a successful save, calls onSaved so the
 * parent can re-fetch and reschedule the reminder.
 *
 * Presentation: a compact `NativeSheet` sized to its one field (rather than the
 * old full-screen `formSheet` page that was ~90% empty). The numeric field
 * auto-focuses on present so the keyboard is up immediately — the deliberate
 * single-field entry exception (distinct from the Today composer's
 * no-auto-focus rule). The date title is human-formatted ("Today", "July 1"),
 * never a raw ISO string.
 *
 * Privacy: weight values are never emitted to logs or error messages.
 */

import { StyleSheet, Text, View } from "react-native";
import { useCallback, useState } from "react";

import {
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import { NativeSheet } from "@/components/ui/NativeSheet";
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
    <NativeSheet
      visible={visible}
      onClose={onClose}
      // A compact sheet sized to its single field — not a full-screen page.
      detents="fitToContents"
      grabberVisible
      cornerRadius={radius.xl}
      backgroundColor={colors.surface}
      accessibilityLabel="Log weight sheet"
    >
      <View testID="weight-log-sheet" style={styles.container}>
        {/* Header — the native grabber and swipe-to-dismiss replace the old
            "Cancel" button, so the title carries a human-formatted date. */}
        <View style={styles.header}>
          <Text style={[styles.title, { color: colors.text }]}>Log weight</Text>
          <Text style={[styles.dateLabel, { color: colors.textSecondary }]}>
            {formatHumanDate(today, today)}
          </Text>
        </View>

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
            autoFocus
            onSubmit={(w) => void handleSubmit(w)}
          />
        </View>
      </View>
    </NativeSheet>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: spacing.base,
    paddingTop: spacing.base,
    paddingBottom: spacing.xl,
    gap: spacing.base,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
  },
  title: {
    fontSize: typeScale.title2,
    fontWeight: "700",
  },
  dateLabel: {
    fontSize: typeScale.subhead,
  },
  inputCard: {
    padding: spacing.base,
  },
});
