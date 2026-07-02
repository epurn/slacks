import { useMemo } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { LogEventDTO } from "@/api/logEvents";
import type { DerivedItem, editDerivedItem } from "@/api/derivedItems";
import { saveFood } from "@/api/savedFoods";
import { EditableItemRow } from "@/components/EditableItemRow";
import { StatusIcon } from "@/components/StatusIcon";
import type { ApiSession } from "@/state/session";
import { statusPresentation } from "@/state/today";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";

/**
 * A single timeline row: a compact status icon, the natural-language text the
 * user logged, and a short status label.
 *
 * When the event has resolved derived food/exercise items, they render beneath
 * the entry as editable item surfaces (FTY-050), letting the user correct
 * calories, macros, servings, and exercise burn in place via the FTY-051 edit
 * endpoint. `items` defaults to none, so an event without derived items (or a
 * caller that has not loaded them yet) renders exactly as before; editing
 * requires the authenticated `session`.
 *
 * Resolved food items show a "Save this food" action (FTY-053): the typed
 * phrase (`event.raw_text`) is passed as the alias to record. `saveFoodFn` is
 * injectable for tests.
 *
 * A `needs_clarification` event renders the legible, *inviting* variant
 * (FTY-149): muted text with a gentle "needs a detail" tag and an explicit
 * "Add a detail" call-to-action, visibly uncounted (a trailing "—"), never a
 * bare/silent row. The whole row is one tap target that opens the clarify sheet
 * via `onPress`; a screen reader hears the needs-a-detail state and that tapping
 * resolves it. This honours "acknowledge every action / no inert outcomes".
 *
 * A `failed` event (the parse couldn't be estimated) renders the calm, actionable
 * variant (FTY-176): muted text with a gentle "Couldn't read that" line and two
 * explicit affordances — **Retry** (re-submit the same text as a fresh attempt)
 * and **Edit as text** (fix the wording, then resubmit) — visibly uncounted
 * (a trailing "—"), never a static dead-end row. Each affordance is its own ≥44pt
 * tap target with a VoiceOver label; the status icon conveys the failed state.
 */
export function EntryRow({
  event,
  items = [],
  session = null,
  editItem,
  onItemChange,
  saveFoodFn = saveFood,
  onPress,
  onRetry,
  onEditAsText,
}: {
  event: LogEventDTO;
  items?: readonly DerivedItem[];
  session?: ApiSession | null;
  editItem?: typeof editDerivedItem;
  onItemChange?: (item: DerivedItem) => void;
  saveFoodFn?: typeof saveFood;
  /**
   * Tap handler for a `needs_clarification` entry — opens the clarify-mode
   * sheet (FTY-149). Ignored for every other status (those rows are not
   * tappable). When omitted, a needs-clarification row still renders legibly,
   * just non-interactive.
   */
  onPress?: () => void;
  /**
   * Retry a `failed` parse (FTY-176) — re-submits the same `raw_text` as a fresh
   * attempt via the create path. Ignored for every other status. When omitted,
   * the failed row still renders legibly, just without the Retry affordance.
   */
  onRetry?: () => void;
  /**
   * Edit a `failed` parse as text (FTY-176) — prefills the composer with the
   * entry's `raw_text` so the user can fix the wording, then resubmit. Ignored
   * for every other status.
   */
  onEditAsText?: () => void;
}) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const { label } = statusPresentation(event.status);

  // Calm, actionable "couldn't read that" row for a failed parse (FTY-176). The
  // status is terminal and uncounted, but the row is never a dead end: Retry
  // re-submits the same text as a fresh attempt and Edit as text hands the
  // wording back to the composer. The status icon + copy convey the failed state
  // to VoiceOver; each affordance is a distinct ≥44pt button.
  if (event.status === "failed") {
    return (
      <View testID="failed-parse-row" style={styles.failedRow}>
        <StatusIcon status={event.status} />
        <View style={styles.body}>
          <Text style={[styles.text, styles.clarifyText]} numberOfLines={2}>
            {event.raw_text}
          </Text>
          <Text style={[styles.failedHint, { color: colors.textMuted }]}>
            Couldn&apos;t read that
          </Text>
          <View style={styles.failedActions}>
            <Pressable
              testID="failed-retry"
              style={({ pressed }) => [
                styles.failedAction,
                pressed && onRetry ? { opacity: 0.6 } : null,
              ]}
              onPress={onRetry}
              disabled={!onRetry}
              accessibilityRole="button"
              accessibilityLabel="Retry"
              accessibilityHint="Re-runs the estimate as a fresh attempt"
            >
              <Text style={[styles.failedActionText, { color: colors.accent }]}>
                Retry
              </Text>
            </Pressable>
            <Pressable
              testID="failed-edit-as-text"
              style={({ pressed }) => [
                styles.failedAction,
                pressed && onEditAsText ? { opacity: 0.6 } : null,
              ]}
              onPress={onEditAsText}
              disabled={!onEditAsText}
              accessibilityRole="button"
              accessibilityLabel="Edit as text"
              accessibilityHint="Puts this entry's wording in the composer to fix and resubmit"
            >
              <Text style={[styles.failedActionText, { color: colors.accent }]}>
                Edit as text
              </Text>
            </Pressable>
          </View>
        </View>
        {/* Visibly uncounted — never a fabricated number for a failed parse. */}
        <Text style={[styles.uncounted, { color: colors.textMuted }]}>—</Text>
      </View>
    );
  }

  // Legible, inviting "needs a detail" row (FTY-149). The status is terminal
  // and uncounted (the daily-summary filter excludes it), but the row makes the
  // missing-detail state and the resolve path unmistakable.
  if (event.status === "needs_clarification") {
    return (
      <Pressable
        testID="add-a-detail-row"
        style={({ pressed }) => [
          styles.clarifyRow,
          pressed && onPress ? { opacity: 0.6 } : null,
        ]}
        onPress={onPress}
        disabled={!onPress}
        accessibilityRole="button"
        accessibilityLabel={`${event.raw_text}, needs a detail, uncounted`}
        accessibilityHint="Tap to add the missing detail so Fatty can count it"
      >
        <StatusIcon status={event.status} />
        <View style={styles.body}>
          <Text
            style={[styles.text, styles.clarifyText]}
            numberOfLines={2}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          >
            {event.raw_text}
          </Text>
          <View style={styles.clarifyMetaRow}>
            <View
              style={[styles.needsDetailTag, { backgroundColor: colors.controlBackground }]}
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            >
              <Text style={[styles.needsDetailText, { color: colors.textMuted }]}>
                needs a detail
              </Text>
            </View>
            <Text
              style={[styles.addDetailCta, { color: colors.accent }]}
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            >
              Add a detail ›
            </Text>
          </View>
        </View>
        {/* Visibly uncounted — never a number standing in for acknowledgement. */}
        <Text
          style={[styles.uncounted, { color: colors.textMuted }]}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        >
          —
        </Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.row}>
        <StatusIcon status={event.status} />
        <View style={styles.body}>
          <Text style={styles.text} numberOfLines={3}>
            {event.raw_text}
          </Text>
          <Text style={styles.meta}>{label}</Text>
        </View>
      </View>
      {session && items.length > 0 ? (
        <View style={styles.items}>
          {items.map((item) => (
            <EditableItemRow
              key={item.id}
              item={item}
              session={session}
              edit={editItem}
              onItemChange={onItemChange}
              logPhrase={event.raw_text}
              saveFood={saveFoodFn}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    container: {
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: colors.separator,
    },
    row: {
      flexDirection: "row",
      alignItems: "center",
      gap: 12,
      paddingVertical: 12,
      paddingHorizontal: 16,
    },
    clarifyRow: {
      flexDirection: "row",
      alignItems: "center",
      gap: 12,
      paddingVertical: 12,
      paddingHorizontal: 16,
      minHeight: 44,
    },
    failedRow: {
      flexDirection: "row",
      alignItems: "center",
      gap: 12,
      paddingVertical: 12,
      paddingHorizontal: 16,
      minHeight: 44,
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: colors.separator,
    },
    failedHint: {
      fontSize: 13,
      marginTop: 2,
    },
    failedActions: {
      flexDirection: "row",
      gap: 20,
      marginTop: 6,
      marginBottom: -6,
    },
    failedAction: {
      minHeight: 44,
      justifyContent: "center",
    },
    failedActionText: {
      fontSize: 14,
      fontWeight: "600",
    },
    body: {
      flex: 1,
    },
    text: {
      fontSize: 16,
      color: colors.text,
    },
    clarifyText: {
      color: colors.textMuted,
    },
    clarifyMetaRow: {
      flexDirection: "row",
      alignItems: "center",
      gap: 8,
      marginTop: 4,
    },
    needsDetailTag: {
      borderRadius: 6,
      paddingHorizontal: 8,
      paddingVertical: 2,
    },
    needsDetailText: {
      fontSize: 12,
      fontWeight: "500",
    },
    addDetailCta: {
      fontSize: 13,
      fontWeight: "600",
    },
    uncounted: {
      fontSize: 16,
      minWidth: 24,
      textAlign: "right",
    },
    meta: {
      fontSize: 13,
      color: colors.textMuted,
      marginTop: 2,
    },
    items: {
      paddingBottom: 8,
    },
  });
}
