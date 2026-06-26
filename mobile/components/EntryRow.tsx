import { StyleSheet, Text, View } from "react-native";

import { StatusIcon } from "@/components/StatusIcon";
import type { TodayEntry } from "@/state/today";

/**
 * A single timeline row: the natural-language text the user logged, a compact
 * status/evidence icon, and the calorie estimate once it resolves.
 */
export function EntryRow({ entry }: { entry: TodayEntry }) {
  return (
    <View style={styles.row}>
      <StatusIcon entry={entry} />
      <View style={styles.body}>
        <Text style={styles.text} numberOfLines={2}>
          {entry.text}
        </Text>
        <Text style={styles.meta}>{kindLabel(entry)}</Text>
      </View>
      <Text style={styles.calories}>{caloriesLabel(entry)}</Text>
    </View>
  );
}

function kindLabel(entry: TodayEntry): string {
  return entry.kind === "food" ? "Food" : "Exercise";
}

function caloriesLabel(entry: TodayEntry): string {
  if (entry.status === "pending" || entry.calories === null) {
    return "—";
  }
  const sign = entry.kind === "exercise" ? "−" : "";
  return `${sign}${entry.calories} kcal`;
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#E5E5EA",
  },
  body: {
    flex: 1,
  },
  text: {
    fontSize: 16,
    color: "#1C1C1E",
  },
  meta: {
    fontSize: 13,
    color: "#8E8E93",
    marginTop: 2,
  },
  calories: {
    fontSize: 15,
    fontVariant: ["tabular-nums"],
    color: "#1C1C1E",
  },
});
