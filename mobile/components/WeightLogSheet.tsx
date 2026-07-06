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

import { Pressable, StyleSheet, Text, View } from "react-native";
import { useCallback, useState } from "react";

import {
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import { DisplayText } from "@/components/ui/DisplayText";
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
  /**
   * E2E-only (FTY-265): when set, renders an invisible, non-interactive marker
   * with this testID once the sheet's content has mounted. The caller only sets
   * this under `isE2EMode()` for the active `weight.sheet` visual-review preset,
   * once its data has settled — undefined in every normal (non-preset) open, so
   * this never renders in a release build or a real user's "+ Log weight" tap.
   * A shared marker rendered outside this sheet (e.g. at the navigator level)
   * cannot work here: a presented native sheet occludes its presenter from the
   * accessibility tree, so screenshot automation would never find it.
   */
  settledMarkerTestID?: string;
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
  settledMarkerTestID,
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
        {/* Header — the native grabber and swipe-to-dismiss are the primary
            dismissal, but a visible, labeled "Cancel" control is kept so the
            affordance is reachable with VoiceOver and by users who don't drag
            the sheet. The title carries a human-formatted date. */}
        <View style={styles.header}>
          <View style={styles.headerTitles}>
            <DisplayText scale="title2">Log weight</DisplayText>
            <Text style={[styles.dateLabel, { color: colors.textSecondary }]}>
              {formatHumanDate(today, today)}
            </Text>
          </View>
          <Pressable
            onPress={onClose}
            accessibilityLabel="Cancel"
            accessibilityRole="button"
            style={styles.closeButton}
          >
            <Text style={[styles.closeLabel, { color: colors.accentText }]}>Cancel</Text>
          </Pressable>
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

        {settledMarkerTestID ? (
          <View
            testID={settledMarkerTestID}
            accessible
            accessibilityLabel={settledMarkerTestID}
            pointerEvents="none"
            style={styles.settledMarker}
          />
        ) : null}
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
    alignItems: "center",
    gap: spacing.sm,
  },
  headerTitles: {
    flex: 1,
    gap: 2,
  },
  dateLabel: {
    fontSize: typeScale.subhead,
  },
  closeButton: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  closeLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  inputCard: {
    padding: spacing.base,
  },
  settledMarker: {
    position: "absolute",
    top: 0,
    left: 0,
    width: 4,
    height: 4,
  },
});
