import { useMemo } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type AccessibilityActionEvent,
} from "react-native";

import type { LogEventDTO } from "@/api/logEvents";
import { StatusIcon } from "@/components/StatusIcon";
import { statusPresentation } from "@/state/today";
import { typeScale, useTheme } from "@/theme";
import type { ColorPalette } from "@/theme/colors";

/**
 * Practical proxy for whether a needs-a-detail row's phrase will clip at
 * `numberOfLines={2}`. RN's `onTextLayout` does not reliably report the
 * untruncated line count once `numberOfLines` is set (behaviour differs by
 * platform), so a character-count threshold approximating two lines of body
 * text in the row's text column stands in.
 */
const TRUNCATION_CHAR_THRESHOLD = 60;

function isLikelyTruncated(text: string): boolean {
  return text.length > TRUNCATION_CHAR_THRESHOLD;
}

/**
 * A single timeline row: a compact status icon, the natural-language text the
 * user logged, and a short status label.
 *
 * A `needs_clarification` event renders the legible, *inviting* variant
 * (FTY-149): muted text with a single "Add a detail ›" affordance chip,
 * visibly uncounted (a trailing "—"), never a bare/silent row. FTY-177
 * collapsed what was previously two controls saying the same thing (a "needs a
 * detail" tag *and* a separate CTA) into that one chip. The whole row is one
 * tap target that opens the clarify sheet via `onPress`, whose header shows the
 * full, untruncated phrase — a truncated phrase in the row carries a "more…"
 * cue plus an accessibility hint saying as much, so a mid-word cut is never a
 * silent dead end. A screen reader hears the needs-a-detail state and that
 * tapping resolves it. This honours "acknowledge every action / no inert
 * outcomes".
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
  onPress,
  onRetry,
  onEditAsText,
  readOnly = false,
  accessibilityActions,
  onAccessibilityAction,
}: {
  event: LogEventDTO;
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
  /**
   * Read-only past-day timeline (FTY-199). A historical day is view-only, so an
   * unresolved `needs_clarification` / `failed` event from that day must render
   * as a calm, non-interactive informational row — never the accent
   * "Add a detail ›" chip or the Retry / Edit-as-text buttons, which would look
   * tappable but do nothing (an inert dead-end the design philosophy forbids
   * under "acknowledge every action"). The state is still legible and conveyed
   * to VoiceOver; there is simply no false affordance. Default off, so Today's
   * interactive rows are unchanged.
   */
  readOnly?: boolean;
  /**
   * Delete custom action (FTY-322), supplied by the swipe wrapper so the
   * destructive Delete stays reachable by VoiceOver on this row's own accessible
   * controls — the swipe gesture is pointer-only. Spread onto the tappable
   * "Add a detail" row (needs_clarification) and onto the Retry / Edit-as-text
   * controls (failed), so a screen-reader user always has Delete on the focused
   * control. Absent for the non-deletable read-only past-day rows.
   */
  accessibilityActions?: readonly { name: string; label: string }[];
  onAccessibilityAction?: (event: AccessibilityActionEvent) => void;
}) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const { label } = statusPresentation(event.status);
  // Delete custom action props, spread onto each variant's accessible controls
  // when the swipe wrapper supplies them (FTY-322). Grouped so a variant that
  // renders several controls attaches the same reachable action to each.
  const deleteA11y =
    accessibilityActions && onAccessibilityAction
      ? { accessibilityActions, onAccessibilityAction }
      : null;

  // Calm, actionable "couldn't read that" row for a failed parse (FTY-176). The
  // status is terminal and uncounted, but the row is never a dead end: Retry
  // re-submits the same text as a fresh attempt and Edit as text hands the
  // wording back to the composer. The status icon + copy convey the failed state
  // to VoiceOver; each affordance is a distinct ≥44pt button.
  if (event.status === "failed") {
    // Read-only past day (FTY-199): a calm "couldn't read that" row with no
    // Retry / Edit-as-text buttons — those would be inert on a historical day.
    // The whole row is one non-interactive a11y element carrying the state.
    if (readOnly) {
      return (
        <View
          testID="failed-parse-row"
          style={styles.failedRow}
          accessible
          accessibilityLabel={`${event.raw_text}, couldn't read that, uncounted`}
        >
          <StatusIcon status={event.status} />
          <View style={styles.body}>
            <Text style={[styles.text, styles.clarifyText]} numberOfLines={2}>
              {event.raw_text}
            </Text>
            <Text style={[styles.failedHint, { color: colors.textMuted }]}>
              Couldn&apos;t read that
            </Text>
          </View>
          {/* Visibly uncounted — never a fabricated number for a failed parse. */}
          <Text style={[styles.uncounted, { color: colors.textMuted }]}>—</Text>
        </View>
      );
    }
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
              {...deleteA11y}
            >
              <Text style={[styles.failedActionText, { color: colors.accentText }]}>
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
              {...deleteA11y}
            >
              <Text style={[styles.failedActionText, { color: colors.accentText }]}>
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
  // missing-detail state and the resolve path unmistakable. FTY-177 collapses
  // the tag+CTA duplication into one chip and adds a truncation hint.
  if (event.status === "needs_clarification") {
    // Read-only past day (FTY-199): a calm "needs a detail" row with no accent
    // "Add a detail ›" chip and no tap target — resolving a clarify is not a
    // historical-day action, so the affordance would be an inert dead-end. The
    // row stays legible and one non-interactive a11y element conveys the state.
    if (readOnly) {
      return (
        <View
          testID="add-a-detail-row"
          style={styles.clarifyRow}
          accessible
          accessibilityLabel={`${event.raw_text}, needs a detail, uncounted`}
        >
          <StatusIcon status={event.status} />
          <View style={styles.body}>
            <Text style={[styles.text, styles.clarifyText]} numberOfLines={2}>
              {event.raw_text}
            </Text>
          </View>
          {/* Visibly uncounted — never a number standing in for acknowledgement. */}
          <Text style={[styles.uncounted, { color: colors.textMuted }]}>—</Text>
        </View>
      );
    }
    const truncated = isLikelyTruncated(event.raw_text);
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
        accessibilityHint="Tap to see the full phrase and add the missing detail"
        {...deleteA11y}
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
          {truncated ? (
            <Text
              testID="add-a-detail-more-hint"
              style={[styles.truncationHint, { color: colors.textMuted }]}
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
            >
              more…
            </Text>
          ) : null}
          {/* Single affordance — replaces the old duplicated "needs a detail"
              tag + separate "Add a detail" CTA with one clear chip. */}
          <View
            style={[styles.addDetailChip, { backgroundColor: colors.controlBackground }]}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          >
            <Text style={[styles.addDetailChipText, { color: colors.accentText }]}>
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
      fontSize: typeScale.footnote,
      marginTop: 2,
    },
    failedActions: {
      flexDirection: "row",
      gap: 20,
      marginTop: 6,
      marginBottom: -6,
    },
    failedAction: {
      minWidth: 44,
      minHeight: 44,
      justifyContent: "center",
    },
    failedActionText: {
      fontSize: typeScale.detail,
      fontWeight: "600",
    },
    body: {
      flex: 1,
    },
    text: {
      fontSize: typeScale.callout,
      color: colors.text,
    },
    clarifyText: {
      color: colors.textMuted,
    },
    truncationHint: {
      fontSize: typeScale.caption1,
      marginTop: 2,
    },
    addDetailChip: {
      alignSelf: "flex-start",
      borderRadius: 6,
      paddingHorizontal: 8,
      paddingVertical: 2,
      marginTop: 4,
    },
    addDetailChipText: {
      fontSize: typeScale.footnote,
      fontWeight: "600",
    },
    uncounted: {
      fontSize: typeScale.callout,
      minWidth: 24,
      textAlign: "right",
    },
    meta: {
      fontSize: typeScale.footnote,
      color: colors.textMuted,
      marginTop: 2,
    },
  });
}
