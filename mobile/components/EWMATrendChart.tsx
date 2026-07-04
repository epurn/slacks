/**
 * Weight trend chart for FTY-101. Renders two visual layers:
 *   1. Raw daily weigh-in points — small, de-emphasised dots.
 *   2. EWMA smoothed trend line — the primary visual lead.
 *
 * Per §4b: "Plot the actual logged weigh-ins as de-emphasized points and
 * overlay the smoothed trend as the primary line." The EWMA line, not any
 * single reading, is the story the chart tells.
 *
 * The plot is drawn with `react-native-svg`: the smoothed trend is a single
 * `Polyline`, and the raw and trend points are `Circle`s. Handles loading,
 * error, empty, and sparse (single-point) states so the chart never looks
 * broken. Accessibility: chart View carries a text summary as an alternative
 * for screen readers.
 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { Circle, Polyline, Svg } from "react-native-svg";

import type { WeightEntryDTO } from "@/api/weightEntries";
import type { UnitsPreference } from "@/state/profile";
import { formatHumanDate, kgToDisplay, weightUnitLabel } from "@/state/weightEntries";
import { useTheme, typeScale } from "@/theme";
import { ThemedNumber } from "@/components/ui";

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
  /** Today as `YYYY-MM-DD`; used to human-format user-facing axis/summary dates. */
  today: string;
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
  today,
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
  const summaryLabel = buildSummary(entries, ewmaDisplay, unit, today);

  if (entries.length === 1) {
    return (
      <View
        accessibilityLabel={summaryLabel}
        accessibilityRole="image"
        style={styles.state}
      >
        <ThemedNumber
          value={`${ewmaDisplay[0]} ${unit}`}
          scale="title2"
        />
        <Text style={[styles.singleDate, { color: colors.textSecondary }]}>
          {formatHumanDate(entries[0]!.effective_date, today)}
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
          today={today}
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
  ewmaDisplay: number[],
  unit: string,
  today: string,
): string {
  if (entries.length === 1) {
    return `Weight trend: ${ewmaDisplay[0]} ${unit} on ${formatHumanDate(entries[0]!.effective_date, today)}`;
  }
  const first = entries[0]!;
  const last = entries[entries.length - 1]!;
  const currentTrend = ewmaDisplay[ewmaDisplay.length - 1]!;
  const startTrend = ewmaDisplay[0]!;
  const delta = Math.round((currentTrend - startTrend) * 10) / 10;
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "stable";
  return (
    `Smoothed weight trend: ${entries.length} readings from ` +
    `${formatHumanDate(first.effective_date, today)} to ${formatHumanDate(last.effective_date, today)}. ` +
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
  today,
  colors,
}: {
  entries: readonly WeightEntryDTO[];
  rawDisplay: number[];
  ewmaDisplay: number[];
  width: number;
  unit: string;
  today: string;
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
  }));

  const linePoints = ewmaPoints.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <View style={{ height: CHART_H, width }}>
      {/* Plot canvas: raw dots, the trend line, and the trend dots. */}
      <Svg width={width} height={CHART_H} style={StyleSheet.absoluteFill}>
        {/* Raw weigh-in dots — de-emphasised */}
        {rawPoints.map((p, i) => (
          <Circle
            key={`raw-dot-${i}`}
            cx={p.x}
            cy={p.y}
            r={RAW_DOT_R}
            fill={colors.textSecondary}
            opacity={RAW_DOT_OPACITY}
          />
        ))}

        {/* EWMA smoothed trend — the primary line */}
        <Polyline
          points={linePoints}
          fill="none"
          stroke={colors.accent}
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* EWMA point dots */}
        {ewmaPoints.map((p, i) => (
          <Circle
            key={`ewma-dot-${i}`}
            cx={p.x}
            cy={p.y}
            r={TREND_DOT_R}
            fill={colors.accent}
          />
        ))}
      </Svg>

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
        {formatHumanDate(entries[0]!.effective_date, today)}
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
        {formatHumanDate(entries[n - 1]!.effective_date, today)}
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
    fontSize: typeScale.subhead,
    textAlign: "center",
    paddingHorizontal: 16,
  },
  singleDate: {
    fontSize: typeScale.detail,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 10,
  },
  retryLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "600",
  },
  axisLabel: {
    fontSize: typeScale.caption2,
    textAlign: "right",
  },
});
