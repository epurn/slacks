/**
 * Weight trend chart for FTY-101. Renders two visual layers:
 *   1. Raw daily weigh-in points — small, de-emphasised dots.
 *   2. EWMA smoothed trend line — the primary visual lead.
 *
 * Per §4b: "Plot the actual logged weigh-ins as de-emphasized points and
 * overlay the smoothed trend as the primary line." The EWMA line, not any
 * single reading, is the story the chart tells.
 *
 * Uses pure React Native Views (no external charting library). Handles
 * loading, error, empty, and sparse (single-point) states so the chart never
 * looks broken. Accessibility: chart View carries a text summary as an
 * alternative for screen readers.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import type { WeightEntryDTO } from "@/api/weightEntries";
import type { UnitsPreference } from "@/state/profile";
import { kgToDisplay, weightUnitLabel } from "@/state/weightEntries";
import { useTheme } from "@/theme";

const CHART_H = 180;
const PAD = { top: 20, bottom: 32, left: 48, right: 12 };
const RAW_DOT_R = 3;
const RAW_DOT_OPACITY = 0.35;
const TREND_DOT_R = 4;

interface EWMATrendChartProps {
  entries: readonly WeightEntryDTO[];
  /** EWMA trend values in canonical kg, same length and order as entries. */
  ewmaKg: readonly number[];
  unitsPreference: UnitsPreference;
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
  /**
   * Canvas width from parent's onLayout. Pass 0 when unmeasured;
   * the chart is hidden until a positive width arrives.
   */
  width: number;
}

export function EWMATrendChart({
  entries,
  ewmaKg,
  unitsPreference,
  loading,
  error,
  onRetry,
  width,
}: EWMATrendChartProps) {
  const { colors } = useTheme();
  const unit = weightUnitLabel(unitsPreference);

  if (loading) {
    return (
      <View style={styles.state}>
        <ActivityIndicator accessibilityLabel="Loading weight trend" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.state}>
        <Text
          style={[styles.stateText, { color: colors.textSecondary }]}
          accessibilityRole="alert"
        >
          {error}
        </Text>
        {onRetry ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Try again"
            onPress={onRetry}
            style={[styles.retry, { backgroundColor: colors.controlBackground }]}
          >
            <Text style={[styles.retryLabel, { color: colors.text }]}>
              Try again
            </Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (entries.length === 0) {
    return (
      <View style={styles.state}>
        <Text style={[styles.stateText, { color: colors.textSecondary }]}>
          Log your first weigh-in
        </Text>
      </View>
    );
  }

  const rawDisplay = entries.map((e) => kgToDisplay(e.weight_kg, unitsPreference));
  const ewmaDisplay = ewmaKg.map((v) => kgToDisplay(v, unitsPreference));
  const summaryLabel = buildSummary(entries, rawDisplay, ewmaDisplay, unit);

  if (entries.length === 1) {
    return (
      <View
        accessibilityLabel={summaryLabel}
        accessibilityRole="image"
        style={styles.state}
      >
        <Text style={[styles.singlePoint, { color: colors.text }]}>
          {`${ewmaDisplay[0]} ${unit}`}
        </Text>
        <Text style={[styles.singleDate, { color: colors.textSecondary }]}>
          {entries[0]!.effective_date}
        </Text>
      </View>
    );
  }

  return (
    <View accessibilityLabel={summaryLabel} accessibilityRole="image">
      {width > 0 ? (
        <ChartCanvas
          entries={entries}
          rawDisplay={rawDisplay}
          ewmaDisplay={ewmaDisplay}
          width={width}
          unit={unit}
          colors={colors}
        />
      ) : (
        <View style={{ height: CHART_H }} />
      )}
    </View>
  );
}

function buildSummary(
  entries: readonly WeightEntryDTO[],
  rawDisplay: number[],
  ewmaDisplay: number[],
  unit: string,
): string {
  if (entries.length === 1) {
    return `Weight trend: ${ewmaDisplay[0]} ${unit} on ${entries[0]!.effective_date}`;
  }
  const first = entries[0]!;
  const last = entries[entries.length - 1]!;
  const currentTrend = ewmaDisplay[ewmaDisplay.length - 1]!;
  const startTrend = ewmaDisplay[0]!;
  const delta = Math.round((currentTrend - startTrend) * 10) / 10;
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "stable";
  return (
    `Smoothed weight trend: ${entries.length} readings from ` +
    `${first.effective_date} to ${last.effective_date}. ` +
    `Trend moved ${dir} by ${Math.abs(delta)} ${unit}. ` +
    `Current smoothed value: ${currentTrend} ${unit}.`
  );
}

interface CanvasColors {
  readonly text: string;
  readonly textSecondary: string;
  readonly textMuted: string;
  readonly accent: string;
}

function ChartCanvas({
  entries,
  rawDisplay,
  ewmaDisplay,
  width,
  unit,
  colors,
}: {
  entries: readonly WeightEntryDTO[];
  rawDisplay: number[];
  ewmaDisplay: number[];
  width: number;
  unit: string;
  colors: CanvasColors;
}) {
  const plotW = width - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;
  const n = entries.length;

  const allValues = [...rawDisplay, ...ewmaDisplay];
  const minV = Math.min(...allValues);
  const maxV = Math.max(...allValues);
  const range = maxV - minV || 1;

  const xOf = (i: number) => (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const yOf = (v: number) => plotH - ((v - minV) / range) * plotH;

  const rawPoints = rawDisplay.map((v, i) => ({
    x: PAD.left + xOf(i),
    y: PAD.top + yOf(v),
  }));
  const ewmaPoints = ewmaDisplay.map((v, i) => ({
    x: PAD.left + xOf(i),
    y: PAD.top + yOf(v),
    v,
  }));

  return (
    <View style={{ height: CHART_H, width }}>
      {/* Y-axis labels */}
      <Text
        style={[
          styles.axisLabel,
          {
            position: "absolute",
            top: PAD.top - 8,
            left: 0,
            width: PAD.left - 4,
            color: colors.textMuted,
          },
        ]}
      >
        {`${maxV} ${unit}`}
      </Text>
      {minV !== maxV ? (
        <Text
          style={[
            styles.axisLabel,
            {
              position: "absolute",
              top: PAD.top + plotH - 8,
              left: 0,
              width: PAD.left - 4,
              color: colors.textMuted,
            },
          ]}
        >
          {`${minV} ${unit}`}
        </Text>
      ) : null}

      {/* Raw data dots — de-emphasised */}
      {rawPoints.map((p, i) => (
        <View
          key={`raw-dot-${i}`}
          testID={`ewma-raw-dot-${i}`}
          style={{
            position: "absolute",
            left: p.x - RAW_DOT_R,
            top: p.y - RAW_DOT_R,
            width: RAW_DOT_R * 2,
            height: RAW_DOT_R * 2,
            borderRadius: RAW_DOT_R,
            backgroundColor: colors.textSecondary,
            opacity: RAW_DOT_OPACITY,
          }}
        />
      ))}

      {/* EWMA trend line segments — the primary line */}
      {ewmaPoints.slice(1).map((p, i) => {
        const p0 = ewmaPoints[i]!;
        const dx = p.x - p0.x;
        const dy = p.y - p0.y;
        const len = Math.sqrt(dx * dx + dy * dy);
        const angle = Math.atan2(dy, dx) * (180 / Math.PI);
        return (
          <View
            key={`ewma-seg-${i}`}
            testID={`ewma-segment-${i}`}
            style={{
              position: "absolute",
              left: (p0.x + p.x) / 2 - len / 2,
              top: (p0.y + p.y) / 2 - 1.5,
              width: len,
              height: 3,
              backgroundColor: colors.accent,
              transform: [{ rotate: `${angle}deg` }],
            }}
          />
        );
      })}

      {/* EWMA point dots */}
      {ewmaPoints.map((p, i) => (
        <View
          key={`ewma-dot-${i}`}
          testID={`ewma-dot-${i}`}
          style={{
            position: "absolute",
            left: p.x - TREND_DOT_R,
            top: p.y - TREND_DOT_R,
            width: TREND_DOT_R * 2,
            height: TREND_DOT_R * 2,
            borderRadius: TREND_DOT_R,
            backgroundColor: colors.accent,
          }}
        />
      ))}

      {/* X-axis: first and last date */}
      <Text
        style={[
          styles.axisLabel,
          {
            position: "absolute",
            top: PAD.top + plotH + 4,
            left: PAD.left,
            color: colors.textMuted,
          },
        ]}
        numberOfLines={1}
      >
        {entries[0]!.effective_date}
      </Text>
      <Text
        style={[
          styles.axisLabel,
          {
            position: "absolute",
            top: PAD.top + plotH + 4,
            right: PAD.right,
            color: colors.textMuted,
          },
        ]}
        numberOfLines={1}
      >
        {entries[n - 1]!.effective_date}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  state: {
    paddingVertical: 32,
    alignItems: "center",
    gap: 12,
  },
  stateText: {
    fontSize: 15,
    textAlign: "center",
    paddingHorizontal: 16,
  },
  singlePoint: {
    fontSize: 22,
    fontWeight: "700",
  },
  singleDate: {
    fontSize: 14,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 10,
  },
  retryLabel: {
    fontSize: 15,
    fontWeight: "600",
  },
  axisLabel: {
    fontSize: 11,
    textAlign: "right",
  },
});
