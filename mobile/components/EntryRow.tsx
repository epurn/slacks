import { StyleSheet, Text, View } from "react-native";

import type { LogEventDTO } from "@/api/logEvents";
import type { DerivedItem, editDerivedItem } from "@/api/derivedItems";
import { saveFood } from "@/api/savedFoods";
import { EditableItemRow } from "@/components/EditableItemRow";
import { StatusIcon } from "@/components/StatusIcon";
import type { ApiSession } from "@/state/session";
import { statusPresentation } from "@/state/today";

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
 */
export function EntryRow({
  event,
  items = [],
  session = null,
  editItem,
  onItemChange,
  saveFoodFn = saveFood,
}: {
  event: LogEventDTO;
  items?: readonly DerivedItem[];
  session?: ApiSession | null;
  editItem?: typeof editDerivedItem;
  onItemChange?: (item: DerivedItem) => void;
  saveFoodFn?: typeof saveFood;
}) {
  const { label } = statusPresentation(event.status);
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

const styles = StyleSheet.create({
  container: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#E5E5EA",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
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
  items: {
    paddingBottom: 8,
  },
});
