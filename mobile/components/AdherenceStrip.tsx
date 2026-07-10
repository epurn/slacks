/**
 * Compact per-day adherence strip for FTY-101.
 *
 * Renders a horizontal scrollable row of cells, one per day in the range.
 * Each cell shows on-target / off-target / no-target / no-data state.
 *
 * Accessibility: color is never the sole signal. Every cell carries an
 * accessibilityLabel (with a human-formatted date, FTY-189) for VoiceOver, and
 * on-target vs. off-target — the pair a sighted colorblind user is most likely
 * to confuse, since both render as a solid fill — carries a redundant
 * non-color cue too: off-target adds a ringed border so its *shape* differs
 * from on-target's plain fill, not just its hue. `no-target` keeps its
 * existing hollow-border shape; `no-data` stays a muted, borderless fill.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import type { AdherenceDay } from "@/state/trends";
import { formatHumanDate } from "@/state/weightEntries";
import { useTheme } from "@/theme";

const CELL_W = 10;
const CELL_H = 24;
const CELL_R = 3;
const CELL_GAP = 2;
const OFF_TARGET_BORDER_W = 2;

interface AdherenceStripProps {
  days: readonly AdherenceDay[];
  /** Today's date (`YYYY-MM-DD`), for humanizing cell labels ("Today"/"Yesterday"). */
  today: string;
  /** Called when the user taps a cell to open that day's timeline. */
  onDayPress?: (date: string) => void;
}

export function AdherenceStrip({ days, today, onDayPress }: AdherenceStripProps) {
  const { colors } = useTheme();
  const scrollRef = useRef<ScrollView>(null);

  const scrollToRecentEnd = useCallback(() => {
    scrollRef.current?.scrollToEnd({ animated: false });
  }, []);

  const rangeKey = useMemo(() => {
    const first = days[0]?.date ?? "";
    const last = days[days.length - 1]?.date ?? "";
    return `${days.length}:${first}:${last}`;
  }, [days]);

  useEffect(() => {
    scrollToRecentEnd();
  }, [rangeKey, scrollToRecentEnd]);

  if (days.length === 0) {
    return null;
  }

  return (
    <ScrollView
      ref={scrollRef}
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.strip}
      accessibilityRole="toolbar"
      accessibilityLabel="Daily intake adherence"
      onContentSizeChange={scrollToRecentEnd}
    >
      {days.map((day) => {
        const cellStyle = resolveCellStyle(day, colors);
        const label = buildCellLabel(day, today);

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
  colors: { accent: string; coral: string; textMuted: string; separator: string; surface: string },
): { backgroundColor: string; borderWidth?: number; borderColor?: string; opacity?: number } {
  switch (day.state) {
    case "on-target":
      return { backgroundColor: colors.accent };
    case "off-target":
      // Ringed border — a non-color cue distinguishing it from on-target's
      // plain fill (see the module comment).
      return {
        backgroundColor: colors.coral,
        borderWidth: OFF_TARGET_BORDER_W,
        borderColor: colors.surface,
      };
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

function buildCellLabel(day: AdherenceDay, today: string): string {
  const date = formatHumanDate(day.date, today);
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
