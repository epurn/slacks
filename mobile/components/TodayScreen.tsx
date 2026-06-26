import { useMemo } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { EntryRow } from "@/components/EntryRow";
import {
  MOCK_TODAY_ENTRIES,
  selectComplete,
  selectPending,
  summarizeDay,
  type TodayEntry,
} from "@/state/today";

/**
 * The Today shell. Renders the day's timeline from local mock state, grouped
 * into pending (awaiting estimation) and logged (resolved) sections. No
 * networking — the mock state stands in for the logging spine (FTY-013).
 */
export function TodayScreen({
  entries = MOCK_TODAY_ENTRIES,
}: {
  entries?: readonly TodayEntry[];
}) {
  const insets = useSafeAreaInsets();
  const { pending, complete, summary } = useMemo(
    () => ({
      pending: selectPending(entries),
      complete: selectComplete(entries),
      summary: summarizeDay(entries),
    }),
    [entries],
  );

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 24 },
      ]}
    >
      <Text style={styles.title} accessibilityRole="header">
        Today
      </Text>

      <View style={styles.summary}>
        <Text style={styles.net}>{summary.net} kcal net</Text>
        <Text style={styles.summaryMeta}>
          {summary.consumed} in · {summary.burned} out
          {summary.pendingCount > 0
            ? ` · ${summary.pendingCount} estimating`
            : ""}
        </Text>
      </View>

      {pending.length > 0 && (
        <Section title="Estimating">
          {pending.map((entry) => (
            <EntryRow key={entry.id} entry={entry} />
          ))}
        </Section>
      )}

      <Section title="Logged">
        {complete.length > 0 ? (
          complete.map((entry) => <EntryRow key={entry.id} entry={entry} />)
        ) : (
          <Text style={styles.empty}>Nothing logged yet.</Text>
        )}
      </Section>
    </ScrollView>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle} accessibilityRole="header">
        {title}
      </Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#F2F2F7",
  },
  content: {
    paddingHorizontal: 16,
  },
  title: {
    fontSize: 34,
    fontWeight: "700",
    color: "#1C1C1E",
  },
  summary: {
    marginTop: 8,
    marginBottom: 16,
  },
  net: {
    fontSize: 22,
    fontWeight: "600",
    color: "#1C1C1E",
  },
  summaryMeta: {
    fontSize: 14,
    color: "#8E8E93",
    marginTop: 2,
  },
  section: {
    marginBottom: 20,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    color: "#8E8E93",
    marginBottom: 8,
    marginLeft: 4,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: 12,
    overflow: "hidden",
  },
  empty: {
    fontSize: 15,
    color: "#8E8E93",
    padding: 16,
  },
});
