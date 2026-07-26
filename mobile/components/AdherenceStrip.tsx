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
 * non-color cue too: off-target is drawn with **square corners** while every
 * other state keeps the rounded `CELL_R` cap, so its *silhouette* differs from
 * on-target's, not just its hue (FTY-431). `no-target` keeps its existing
 * hollow-border shape; `no-data` stays a muted, borderless fill.
 *
 * That corner cue replaced FTY-189's original `surface`-colored ring: in dark
 * mode `surface` is near-black, so the ring drew a literal black outline around
 * the coral bar that read as broken next to the clean amber on-target bar
 * (operator dogfood 2026-07-26). The shape cue carries no scheme-dependent
 * color of its own, so the coral fill now reads as clean as the amber one in
 * both schemes while staying distinguishable without hue.
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
/** Off-target's non-color cue: square corners against every other state's `CELL_R` cap. */
const OFF_TARGET_CELL_R = 0;

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
  colors: { accent: string; coral: string; textMuted: string; separator: string },
): {
  backgroundColor: string;
  borderRadius?: number;
  borderWidth?: number;
  borderColor?: string;
  opacity?: number;
} {
  switch (day.state) {
    case "on-target":
      return { backgroundColor: colors.accent };
    case "off-target":
      // A clean coral fill with square corners — the non-color cue is the
      // silhouette, not a border, so nothing scheme-colored is painted on top
      // of the bar in either scheme (see the module comment).
      return {
        backgroundColor: colors.coral,
        borderRadius: OFF_TARGET_CELL_R,
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
