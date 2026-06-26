import { StyleSheet, Text, View } from "react-native";

import type { LogEventDTO } from "@/api/logEvents";
import { StatusIcon } from "@/components/StatusIcon";
import { statusPresentation } from "@/state/today";

/**
 * A single timeline row: a compact status icon, the natural-language text the
 * user logged, and a short status label. Event-level detail only — derived
 * food/exercise items and calories arrive with the estimator stories (M4/M5).
 */
export function EntryRow({ event }: { event: LogEventDTO }) {
  const { label } = statusPresentation(event.status);
  return (
    <View style={styles.row}>
      <StatusIcon status={event.status} />
      <View style={styles.body}>
        <Text style={styles.text} numberOfLines={3}>
          {event.raw_text}
        </Text>
        <Text style={styles.meta}>{label}</Text>
      </View>
    </View>
  );
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
});
