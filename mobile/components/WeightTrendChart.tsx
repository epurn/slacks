import { useMemo } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import type { WeightEntryDTO } from "@/api/weightEntries";
import type { UnitsPreference } from "@/state/profile";
import { kgToDisplay, weightUnitLabel } from "@/state/weightEntries";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";

const CHART_H = 160;
const PAD = { top: 16, bottom: 28, left: 48, right: 12 };
const DOT_R = 4;

interface WeightTrendChartProps {
  entries: readonly WeightEntryDTO[];
  unitsPreference: UnitsPreference;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
  /**
   * Canvas width supplied by the parent via `onLayout`. Pass 0 when unmeasured;
   * the chart area is hidden until a positive width is received.
   * In tests, pass a fixed width (e.g. 300) to render the canvas directly.
   */
  width: number;
}

/**
 * Weight trend chart for FTY-074. Renders the user's logged weight entries as a
 * simple line chart over the fetched range, using React Native Views (no external
 * charting dependency). Handles loading, error, empty, and sparse single-point
 * states so the chart never looks broken.
 *
 * Values are displayed in the user's preferred units; the canonical kg from
 * FTY-070 responses is converted at render time via `kgToDisplay`.
 *
 * Accessibility: the chart View carries an accessibilityLabel summarising the
 * trend as a text alternative for screen readers.
 */
export function WeightTrendChart({
  entries,
  unitsPreference,
  loading,
  error,
  onRetry,
  width,
}: WeightTrendChartProps) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const unit = weightUnitLabel(unitsPreference);

  if (loading) {
    return (
      <View style={styles.state}>
        <ActivityIndicator accessibilityLabel="Loading your weight trend" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.state}>
        <Text style={styles.stateText} accessibilityRole="alert">
          {error}
        </Text>
        {onRetry ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Try again"
            onPress={onRetry}
            style={styles.retry}
          >
            <Text style={styles.retryLabel}>Try again</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (entries.length === 0) {
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          No weight entries yet. Log your first weight above.
        </Text>
      </View>
    );
  }

  const displayValues = entries.map((e) => kgToDisplay(e.weight_kg, unitsPreference));
  const summaryLabel = buildSummary(entries, displayValues, unit);

  // Single-point: render a text value, no line needed.
  if (entries.length === 1) {
    return (
      <View
        accessibilityLabel={summaryLabel}
        accessibilityRole="image"
        style={styles.state}
      >
        <Text style={styles.singlePoint}>{`${displayValues[0]} ${unit}`}</Text>
        <Text style={styles.singleDate}>{entries[0].effective_date}</Text>
      </View>
    );
  }

  return (
    <View accessibilityLabel={summaryLabel} accessibilityRole="image">
      {width > 0 ? (
        <ChartCanvas
          entries={entries}
          displayValues={displayValues}
          width={width}
          unit={unit}
          colors={colors}
        />
      ) : (
        // Placeholder until the parent measures its width via onLayout.
        <View style={{ height: CHART_H }} />
      )}
    </View>
  );
}

function buildSummary(
  entries: readonly WeightEntryDTO[],
  displayValues: number[],
  unit: string,
): string {
  if (entries.length === 1) {
    return `Weight: ${displayValues[0]} ${unit} on ${entries[0].effective_date}`;
  }
  const first = entries[0];
  const last = entries[entries.length - 1];
  return (
    `Weight trend: ${entries.length} entries, ` +
    `${displayValues[0]} ${unit} on ${first.effective_date} to ` +
    `${displayValues[displayValues.length - 1]} ${unit} on ${last.effective_date}`
  );
}

function ChartCanvas({
  entries,
  displayValues,
  width,
  unit,
  colors,
}: {
  entries: readonly WeightEntryDTO[];
  displayValues: number[];
  width: number;
  unit: string;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const plotW = width - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;
  const n = entries.length;

  const minV = Math.min(...displayValues);
  const maxV = Math.max(...displayValues);

  const xOf = (i: number) => (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yOf = (v: number) =>
    minV === maxV ? plotH / 2 : plotH - ((v - minV) / (maxV - minV)) * plotH;

  const points = displayValues.map((v, i) => ({
    x: PAD.left + xOf(i),
    y: PAD.top + yOf(v),
    v,
  }));

  return (
    <View style={{ height: CHART_H, width }}>
      {/* Y-axis max label */}
      <Text
        style={[styles.axisLabel, { position: "absolute", top: PAD.top - 8, left: 0, width: PAD.left - 4 }]}
      >{`${maxV} ${unit}`}</Text>
      {/* Y-axis min label (only if different from max) */}
      {minV !== maxV ? (
        <Text
          style={[styles.axisLabel, { position: "absolute", top: PAD.top + plotH - 8, left: 0, width: PAD.left - 4 }]}
        >{`${minV} ${unit}`}</Text>
      ) : null}

      {/* Line segments: thin rotated Views between adjacent data points */}
      {points.slice(1).map((p, i) => {
        const p0 = points[i];
        const dx = p.x - p0.x;
        const dy = p.y - p0.y;
        const len = Math.sqrt(dx * dx + dy * dy);
        const angle = Math.atan2(dy, dx) * (180 / Math.PI);
        const cx = (p0.x + p.x) / 2;
        const cy = (p0.y + p.y) / 2;
        return (
          <View
            key={`seg-${i}`}
            testID={`weight-segment-${i}`}
            style={{
              position: "absolute",
              left: cx - len / 2,
              top: cy - 1,
              width: len,
              height: 2,
              backgroundColor: colors.accent,
              transform: [{ rotate: `${angle}deg` }],
            }}
          />
        );
      })}

      {/* Data point dots */}
      {points.map((p, i) => (
        <View
          key={`dot-${i}`}
          testID={`weight-dot-${i}`}
          style={{
            position: "absolute",
            left: p.x - DOT_R,
            top: p.y - DOT_R,
            width: DOT_R * 2,
            height: DOT_R * 2,
            borderRadius: DOT_R,
            backgroundColor: colors.accent,
          }}
        />
      ))}

      {/* X-axis: first and last date */}
      <Text
        style={[styles.axisLabel, { position: "absolute", top: PAD.top + plotH + 4, left: PAD.left }]}
        numberOfLines={1}
      >
        {entries[0].effective_date}
      </Text>
      <Text
        style={[styles.axisLabel, { position: "absolute", top: PAD.top + plotH + 4, right: PAD.right }]}
        numberOfLines={1}
      >
        {entries[n - 1].effective_date}
      </Text>
    </View>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    state: {
      paddingVertical: 32,
      alignItems: "center",
      gap: 12,
    },
    stateText: {
      fontSize: 15,
      color: colors.textMuted,
      textAlign: "center",
      paddingHorizontal: 16,
    },
    singlePoint: {
      fontSize: 22,
      fontWeight: "700",
      color: colors.text,
    },
    singleDate: {
      fontSize: 14,
      color: colors.textMuted,
    },
    retry: {
      paddingVertical: 10,
      paddingHorizontal: 20,
      borderRadius: 10,
      backgroundColor: colors.controlBackground,
    },
    retryLabel: {
      fontSize: 15,
      fontWeight: "600",
      color: colors.text,
    },
    axisLabel: {
      fontSize: 11,
      color: colors.textMuted,
      textAlign: "right",
    },
  });
}
