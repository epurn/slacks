/**
 * Settled content states for the Trends intake-adherence card, extracted from
 * TrendsScreen (FTY-365) — presentational only; the screen owns the data read
 * and phase derivation.
 */

import { StyleSheet, Text, View } from "react-native";

import type { AdherenceSummary } from "@/state/trends";
import { spacing, typeScale } from "@/theme";

type AdherenceColors = {
  text: string;
  textSecondary: string;
  textMuted: string;
};

/**
 * The honest empty invite: genuinely nothing logged in the range. Distinct from
 * the uncounted state — here there are no entries at all, so we invite logging
 * rather than claim a false "no intake data" (FTY-188).
 */
export function AdherenceEmptyInvite({ colors }: { colors: AdherenceColors }) {
  return (
    <View
      style={styles.adherenceRow}
      accessible
      accessibilityLabel="No intake logged for this range"
    >
      <Text style={[styles.emptyTitle, { color: colors.text }]}>
        No meals logged in this range yet.
      </Text>
      <Text style={[styles.emptyText, { color: colors.textSecondary }]}>
        Your logged meals will show up here.
      </Text>
    </View>
  );
}

/**
 * The logged-but-uncounted state: entries exist in the range but none are
 * counted yet (they await a detail on Today). Never the false "No intake data"
 * — this acknowledges the real action and points at what to do next without
 * duplicating the Today clarify flow (ux-design §Acknowledge-every-action;
 * FTY-188).
 */
export function AdherenceUncountedRow({
  count,
  colors,
}: {
  count: number;
  colors: AdherenceColors;
}) {
  const noun = count === 1 ? "entry" : "entries";
  return (
    <View
      style={styles.adherenceRow}
      accessible
      accessibilityLabel={`${count} ${noun} awaiting details`}
    >
      <Text style={[styles.emptyTitle, { color: colors.text }]}>
        {`${count} ${noun} awaiting details`}
      </Text>
      <Text style={[styles.emptyText, { color: colors.textSecondary }]}>
        Add their details on Today to count them toward your intake.
      </Text>
    </View>
  );
}

export function AdherenceSummaryRow({
  adherence,
  colors,
}: {
  adherence: AdherenceSummary;
  colors: AdherenceColors;
}) {
  return (
    <View style={styles.adherenceRow}>
      {adherence.avgCalories !== null ? (
        <Text
          style={[styles.adherenceStat, { color: colors.text }]}
          accessibilityLabel={`Average: ${adherence.avgCalories} kcal per day`}
        >
          {`Avg ${adherence.avgCalories} kcal/day`}
        </Text>
      ) : null}
      {adherence.daysWithTarget > 0 ? (
        <Text
          style={[styles.adherenceStat, { color: colors.textSecondary }]}
          accessibilityLabel={`On target: ${adherence.daysOnTarget} of ${adherence.daysWithTarget} days`}
        >
          {`${adherence.daysOnTarget}/${adherence.daysWithTarget} days on target`}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  adherenceRow: { gap: spacing.xs },
  emptyTitle: { fontSize: typeScale.body, fontWeight: "600" },
  emptyText: { fontSize: typeScale.body },
  adherenceStat: { fontSize: typeScale.subhead },
});
