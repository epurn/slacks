/**
 * Compact per-day adherence strip for FTY-101.
 *
 * Renders a horizontal scrollable row of cells, one per day in the range.
 * Each cell shows on-target / off-target / no-target / no-data state.
 *
 * Accessibility: color is never the sole signal — each cell carries an
 * accessibilityLabel and uses shape (filled vs. hollow) alongside color
 * so the strip is readable with VoiceOver and in non-color modes.
 */

import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import type { AdherenceDay } from "@/state/trends";
import { useTheme } from "@/theme";

const CELL_W = 10;
const CELL_H = 24;
const CELL_R = 3;
const CELL_GAP = 2;

interface AdherenceStripProps {
  days: readonly AdherenceDay[];
  /** Called when the user taps a cell to open that day's timeline. */
  onDayPress?: (date: string) => void;
}

export function AdherenceStrip({ days, onDayPress }: AdherenceStripProps) {
  const { colors } = useTheme();

  if (days.length === 0) {
    return null;
  }

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.strip}
      accessibilityRole="toolbar"
      accessibilityLabel="Daily intake adherence"
    >
      {days.map((day) => {
        const cellStyle = resolveCellStyle(day, colors);
        const label = buildCellLabel(day);

        return (
          <Pressable
            key={day.date}
            testID={`adherence-cell-${day.date}`}
            accessibilityRole="button"
            accessibilityLabel={label}
            accessibilityHint="Opens this day's timeline"
            onPress={onDayPress ? () => onDayPress(day.date) : undefined}
            style={styles.cellWrapper}
          >
            <View style={[styles.cell, cellStyle]} />
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function resolveCellStyle(
  day: AdherenceDay,
  colors: { accent: string; coral: string; textMuted: string; separator: string },
): { backgroundColor: string; borderWidth?: number; borderColor?: string; opacity?: number } {
  switch (day.state) {
    case "on-target":
      return { backgroundColor: colors.accent };
    case "off-target":
      return { backgroundColor: colors.coral };
    case "no-target":
      return {
        backgroundColor: "transparent",
        borderWidth: 1,
        borderColor: colors.textMuted,
        opacity: 0.6,
      };
    case "no-data":
    default:
      return { backgroundColor: colors.separator };
  }
}

function buildCellLabel(day: AdherenceDay): string {
  const date = day.date;
  switch (day.state) {
    case "on-target":
      return `${date}: on target`;
    case "off-target":
      return `${date}: off target`;
    case "no-target":
      return `${date}: no target set`;
    case "no-data":
    default:
      return `${date}: no data`;
  }
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: "row",
    alignItems: "center",
    gap: CELL_GAP,
    paddingVertical: 4,
  },
  cellWrapper: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  cell: {
    width: CELL_W,
    height: CELL_H,
    borderRadius: CELL_R,
  },
});
