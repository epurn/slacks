/**
 * Past-day detail route: /day?date=YYYY-MM-DD
 *
 * Shows the DailySummary for a historical date, reusing the same data the
 * Today screen renders. Per FTY-101 §4b: "tapping a day opens that day's
 * timeline — reuse the Today layout for the selected date." This screen
 * provides the daily summary view for the chosen date. Full log-event history
 * for past days requires a separate API extension (future story).
 */

import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  getDailySummary as getDailySummaryApi,
  DailySummaryApiError,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import { DailySummary } from "@/components/DailySummary";
import { useSession, toApiSession } from "@/state/session";
import { formatDate, formatHumanDate } from "@/state/weightEntries";
import { useTheme, spacing, typeScale, radius } from "@/theme";

function messageFor(error: unknown): string {
  return error instanceof DailySummaryApiError
    ? error.message
    : "Couldn't load this day's summary.";
}

export default function DayScreen() {
  const { date } = useLocalSearchParams<{ date?: string }>();
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const liveSession = useSession();
  const apiSession = useMemo(
    () => (liveSession ? toApiSession(liveSession) : null),
    [liveSession],
  );

  const [summary, setSummary] = useState<DailySummaryDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!apiSession || !date) return;
    let active = true;
    getDailySummaryApi(
      {
        baseUrl: apiSession.baseUrl,
        token: apiSession.token,
        userId: apiSession.userId,
      },
      date,
    ).then(
      (s) => {
        if (!active) return;
        setSummary(s);
        setError(null);
        setLoading(false);
      },
      (err: unknown) => {
        if (!active) return;
        setError(messageFor(err));
        setLoading(false);
      },
    );
    return () => { active = false; };
  }, [apiSession, date]);

  const handleBack = useCallback(() => {
    router.back();
  }, [router]);

  return (
    <ScrollView
      style={[styles.screen, { backgroundColor: colors.surface }]}
      contentContainerStyle={[
        styles.content,
        {
          paddingTop: insets.top + spacing.base,
          paddingBottom: insets.bottom + spacing.xl,
        },
      ]}
    >
      {/* Header */}
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={handleBack}
          style={styles.backBtn}
        >
          <Text style={[styles.backLabel, { color: colors.accent }]}>‹ Trends</Text>
        </Pressable>
        <Text
          style={[styles.dateTitle, { color: colors.text }]}
          accessibilityRole="header"
        >
          {date ? formatHumanDate(date, formatDate(new Date())) : ""}
        </Text>
      </View>

      {loading ? (
        <Text style={[styles.stateText, { color: colors.textSecondary }]}>
          Loading...
        </Text>
      ) : error ? (
        <Text
          style={[styles.stateText, { color: colors.coral }]}
          accessibilityRole="alert"
        >
          {error}
        </Text>
      ) : summary ? (
        <View
          style={[
            styles.card,
            { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
          ]}
        >
          <DailySummary summary={summary} />
        </View>
      ) : (
        <Text style={[styles.stateText, { color: colors.textSecondary }]}>
          No data for this day.
        </Text>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingHorizontal: spacing.base, gap: spacing.base },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.base,
    marginBottom: spacing.sm,
  },
  backBtn: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  backLabel: { fontSize: typeScale.body, fontWeight: "500" },
  dateTitle: { fontSize: typeScale.title2, fontWeight: "700" },
  stateText: { fontSize: typeScale.body },
  card: { padding: spacing.base },
});
