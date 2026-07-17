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
 *
 * Draw-in (FTY-380): the resolved multi-point chart reveals with a calm,
 * one-shot entrance — the canvas fades in while the trend line strokes on left
 * to right (`strokeDashoffset` on an `Animated`-wrapped polyline, JS driver,
 * matching the CalorieHero bar precedent). The reveal plays once per
 * data-settle (loading → data, or a range/data change), never on an unrelated
 * re-render or theme toggle, and degrades to an instant fully-drawn render
 * under Reduce Motion. The SVG canvas keeps its measured height throughout, so
 * nothing below the chart shifts.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  AccessibilityInfo,
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Circle, Polyline, Svg } from "react-native-svg";

import type { WeightEntryDTO } from "@/api/weightEntries";
import type { UnitsPreference } from "@/state/profile";
import { formatHumanDate, kgToDisplay, weightUnitLabel } from "@/state/weightEntries";
import { useTheme, typeScale } from "@/theme";
import { reducedMotionDuration } from "@/theme/motion";
import { ThemedNumber } from "@/components/ui";

const CHART_H = 180;
const PAD = { top: 20, bottom: 32, left: 48, right: 12 };
const RAW_DOT_R = 3;
const RAW_DOT_OPACITY = 0.35;
const TREND_DOT_R = 4;

/** Duration of the one-shot draw-in — a short ease, within the ≤ ~400 ms calm bar. */
const DRAW_IN_MS = 400;
/**
 * Progress fraction by which the canvas fade completes. The dots (and axis-side
 * of the line) are fully visible early, then the stroke reveal carries the rest
 * of the beat — one coherent reveal, no per-dot stagger.
 */
const OPACITY_RAMP_END = 0.3;
/**
 * Upper bound (ms) the armed reveal may wait for the Reduce Motion read before
 * revealing anyway. Mirrors theme/motion.ts (its constant is private): past the
 * deadline the setting is still unknown, so the chart reveals with the
 * no-motion fade — never a stroke sweep, and never left suppressed behind a
 * hung accessibility read (FTY-379).
 */
const REDUCE_MOTION_READ_DEADLINE_MS = 400;

const AnimatedPolyline = Animated.createAnimatedComponent(Polyline);

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
  /**
   * Identity of the range whose data is currently displayed — updated by the
   * caller when a range switch's refetch RESOLVES, not when the switch is
   * tapped (FTY-380). A range switch is a user-initiated data-settle, so it
   * replays the draw-in even when the refetched series happens to be
   * content-identical (e.g. every entry already fell inside the old window);
   * keying on settle (not tap) means exactly one reveal per switch. Passive
   * same-range refetches (a focus gain) keep the same key and stay still.
   */
  rangeKey?: string;
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
  rangeKey = "",
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
          rangeKey={rangeKey}
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

/**
 * Nullable Reduce Motion read: `null` while the async read is in flight, then
 * the live boolean. Local to the chart because the draw-in plays exactly once
 * per data-settle, so it must wait for the setting to be known before choosing
 * reveal-vs-instant — the coalesced `useReduceMotion()` would mark the reveal
 * played (statically) whenever data settles faster than the accessibility
 * read, which the hermetic E2E fetch routinely does. theme/motion.ts holds the
 * same nullable form privately and is FTY-379's boundary (not edited here).
 */
function useReduceMotionRead(): boolean | null {
  const [reduceMotion, setReduceMotion] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then(
      (enabled) => {
        if (mounted) setReduceMotion(enabled);
      },
      () => {
        if (mounted) setReduceMotion(true);
      },
    );
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      (enabled) => setReduceMotion(enabled),
    );
    return () => {
      mounted = false;
      // Defensive: a stubbed AccessibilityInfo may not return a subscription.
      subscription?.remove?.();
    };
  }, []);

  return reduceMotion;
}

interface DrawInRender {
  /** Opacity for the SVG canvas wrapper (static 0/1 or the animated ramp). */
  canvasOpacity: number | Animated.AnimatedInterpolation<number>;
  /** Stroke-reveal props for the trend polyline; null when not revealing. */
  lineDashProps: {
    strokeDasharray: [number, number];
    strokeDashoffset: Animated.AnimatedInterpolation<number>;
  } | null;
}

/**
 * One-shot draw-in for the resolved multi-point chart. The caller remounts the
 * plot (via `key={dataKey}`) whenever the loaded series' content changes, so a
 * mount IS a data-settle: the reveal plays exactly once per mount and an
 * unrelated re-render, scroll, or theme toggle — same key, no remount —
 * renders statically. Under Reduce Motion the chart renders instantly, fully
 * drawn. Until the Reduce Motion read settles (bounded — FTY-379) the canvas
 * holds at opacity 0 inside its fixed-height frame: no layout shift, and no
 * first-frame flash of the finished chart.
 *
 * The render mode is derived — `settled`/`deadlinePassed` are set only from
 * the animation-completion / timer callbacks, never synchronously in the
 * effect body.
 */
function useChartDrawIn(lineLength: number): DrawInRender {
  const reduceMotion = useReduceMotionRead();
  // Lazy state so the Animated.Value is created once and stable across renders.
  const [progress] = useState(() => new Animated.Value(0));
  // The reveal/fade ran to completion — resting render from here on.
  const [settled, setSettled] = useState(false);
  // The Reduce Motion read outlived its bounded wait (FTY-379).
  const [deadlinePassed, setDeadlinePassed] = useState(false);
  // The one-shot has been consumed (animation started, or instant-rendered
  // under Reduce Motion) — a later Reduce Motion toggle must not replay it.
  const playedRef = useRef(false);

  useEffect(() => {
    if (settled || playedRef.current) return;
    if (reduceMotion === null && !deadlinePassed) {
      // The accessibility read is still in flight; bound the wait. Settling in
      // time clears the timer (this effect re-runs on `reduceMotion`).
      const deadline = setTimeout(
        () => setDeadlinePassed(true),
        REDUCE_MOTION_READ_DEADLINE_MS,
      );
      return () => clearTimeout(deadline);
    }
    playedRef.current = true;
    if (reduceMotion) {
      // Reduce Motion: instant, fully drawn — no reveal. The snap keeps the
      // progress consistent should the setting toggle off later.
      progress.setValue(1);
      return;
    }
    // Known motion-ok → the full reveal; deadline passed with the setting
    // still unknown → the short no-motion fade (mirrors theme/motion.ts).
    Animated.timing(progress, {
      toValue: 1,
      duration: deadlinePassed ? reducedMotionDuration : DRAW_IN_MS,
      // A plain ease-out: calm, no bounce, no overshoot (a spring can
      // overshoot and would scrub the stroke reveal past its end).
      ...(deadlinePassed ? {} : { easing: Easing.out(Easing.cubic) }),
      // Drives strokeDashoffset, which can't use the native driver (JS
      // driver, matching the CalorieHero bar precedent).
      useNativeDriver: false,
    }).start(({ finished }) => {
      if (finished) setSettled(true);
    });
  }, [reduceMotion, deadlinePassed, settled, progress]);

  // Derived render mode: static (resting/Reduce Motion) · revealing (fade +
  // stroke sweep) · fading (read never settled — fully-drawn line, quick
  // opacity fade only) · hidden (read pending, within the bounded wait).
  const mode =
    settled || reduceMotion === true
      ? "static"
      : reduceMotion === false
        ? "revealing"
        : deadlinePassed
          ? "fading"
          : "hidden";
  if (mode === "static") return { canvasOpacity: 1, lineDashProps: null };
  if (mode === "hidden") return { canvasOpacity: 0, lineDashProps: null };
  return {
    canvasOpacity: progress.interpolate({
      inputRange: [0, OPACITY_RAMP_END, 1],
      outputRange: [0, 1, 1],
    }),
    lineDashProps:
      mode === "revealing"
        ? {
            strokeDasharray: [lineLength, lineLength],
            strokeDashoffset: progress.interpolate({
              inputRange: [0, 1],
              outputRange: [lineLength, 0],
            }),
          }
        : null,
  };
}

function ChartCanvas({
  entries,
  rawDisplay,
  ewmaDisplay,
  width,
  unit,
  today,
  colors,
  rangeKey,
}: {
  entries: readonly WeightEntryDTO[];
  rawDisplay: number[];
  ewmaDisplay: number[];
  width: number;
  unit: string;
  today: string;
  colors: CanvasColors;
  rangeKey: string;
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

  // Data-settle signature: the plot remounts — and its one-shot draw-in
  // replays — when the loaded series' content changes (loading → data, a new
  // weigh-in) or the user switches range (`rangeKey`, a data-settle even when
  // the refetched series is content-identical). A same-range refetch
  // returning identical data, a theme/units toggle, or an unrelated re-render
  // keeps the mounted, settled plot.
  const dataKey = useMemo(
    () =>
      `${rangeKey}::${entries
        .map((e) => `${e.id}:${e.weight_kg}:${e.effective_date}`)
        .join("|")}`,
    [rangeKey, entries],
  );

  return (
    <View style={{ height: CHART_H, width }}>
      <RevealingPlot
        key={dataKey}
        rawPoints={rawPoints}
        ewmaPoints={ewmaPoints}
        linePoints={linePoints}
        width={width}
        colors={colors}
      />

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

/**
 * The SVG plot — raw dots, the trend line, and the trend dots — wrapped in the
 * one-shot draw-in (FTY-380). Mounted with `key={dataKey}`, so a mount is a
 * data-settle and the reveal plays exactly once per data set. The wrapper
 * fills the fixed-height chart frame, so the reveal never shifts the axis
 * labels or content below.
 */
function RevealingPlot({
  rawPoints,
  ewmaPoints,
  linePoints,
  width,
  colors,
}: {
  rawPoints: { x: number; y: number }[];
  ewmaPoints: { x: number; y: number }[];
  linePoints: string;
  width: number;
  colors: CanvasColors;
}) {
  // Total path length of the trend polyline, for the stroke reveal.
  let lineLength = 0;
  for (let i = 1; i < ewmaPoints.length; i++) {
    lineLength += Math.hypot(
      ewmaPoints[i]!.x - ewmaPoints[i - 1]!.x,
      ewmaPoints[i]!.y - ewmaPoints[i - 1]!.y,
    );
  }
  const { canvasOpacity, lineDashProps } = useChartDrawIn(lineLength);

  return (
    <Animated.View
      testID="ewma-chart-canvas"
      style={[StyleSheet.absoluteFill, { opacity: canvasOpacity }]}
    >
      <Svg width={width} height={CHART_H}>
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

        {/* EWMA smoothed trend — the primary line. Dash props are present only
            mid-reveal; the resting render carries none, so the settled chart
            is pixel-identical to the static one. */}
        <AnimatedPolyline
          points={linePoints}
          fill="none"
          stroke={colors.accent}
          strokeWidth={3}
          strokeLinejoin="round"
          strokeLinecap="round"
          {...(lineDashProps ?? {})}
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
    </Animated.View>
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
