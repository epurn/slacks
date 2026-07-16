/**
 * Trends screen for FTY-101. Rebuilt against the FTY-097 design system.
 *
 * Layout (§4b): weight outcome up top, intake behaviour beneath it. The EWMA
 * smoothed trend line — not any single reading — is the visual lead.
 *
 * Four features:
 *   1. Smoothed weight-trend line (EWMA) over raw daily points with range selector
 *      and headline delta.
 *   2. Intake-adherence summary (avg kcal vs. target, days-on-target, strip).
 *   3. Past-day drilldown — tapping a day opens that day's timeline.
 *   4. "Log weight" — a compact, secondary control on the weight card that opens
 *      a numeric entry sheet, seeded with the last value.
 *
 * Weigh-in cadence lives only in Profile → Preferences (FTY-187; §4c). Logging a
 * weight here still persists the last-weigh-in date and reschedules the
 * due-only reminder via `onWeightLogged`, since that's the only place the date
 * updates and Preferences' cadence control reads it.
 *
 * Privacy: no weight or nutrition values in logs, error messages, or
 * notification bodies.
 *
 * Data freshness (FTY-365): the tab stays mounted across tab switches, so the
 * weight and adherence reads refresh once per focus gain (never a timer) and
 * the date window derives from the clock at focus time, not first mount —
 * deletes and new logs on Today, and day rollovers, appear on the next visit.
 *
 * All injectable for tests: session, API functions, the clock, the focus
 * signal, cadence/notification adapters.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  AppIcon,
  ScreenHeader,
  SegmentedControl,
  Skeleton,
  ThemedNumber,
  floatingSwitcherClearance,
} from "@/components/ui";

import {
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  listWeightEntries as listWeightEntriesApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import {
  DailySummaryApiError,
  getDailySummaryRange as getDailySummaryRangeApi,
  type DailySummaryDTO,
  type DailySummarySession,
} from "@/api/dailySummary";
import type { GoalDirection } from "@/api/goals";
import { AdherenceStrip } from "@/components/AdherenceStrip";
import { EWMATrendChart } from "@/components/EWMATrendChart";
import { WeightLogSheet } from "@/components/WeightLogSheet";
import {
  AdherenceEmptyInvite,
  AdherenceSummaryRow,
  AdherenceUncountedRow,
} from "@/components/trends/AdherenceCardContent";
import { useFocusRefresh } from "@/components/trends/useFocusRefresh";
import { isE2EMode } from "@/e2e/launchMode";
import { registerVisualReviewPreset, useVisualReviewCore } from "@/e2e/visualReview";
// Registers the `trends.adherence_retry` visual-review preset (FTY-264) as a
// side effect, so the deep-link route can find it. See the module doc there —
// this import has no effect outside an active visual-review session.
import "@/components/trends/visualReviewPresets";
import { useGoalDirection } from "@/state/goalDirection";
import type { UnitsPreference } from "@/state/profile";
import { useSession, toApiSession, type Session, type ApiSession } from "@/state/session";
import { useScreenActive } from "@/state/useScreenActive";
import { formatDate } from "@/state/weightEntries";
import {
  DEFAULT_DATE_RANGE,
  DATE_RANGE_OPTIONS,
  computeEWMAFromEntries,
  computeHeadlineDelta,
  computeAdherence,
  adherenceContentState,
  rangeBounds,
  rangeProse,
  resolveDeltaGoalState,
  buildDayRange,
  type DateRangeKey,
  type AdherenceSummary,
} from "@/state/trends";
import {
  onWeightLogged,
  type NotificationsAdapter,
  type CadenceStore,
} from "@/state/reminderScheduler";
import { useTheme, spacing, typeScale, radius } from "@/theme";

type LoadPhase = "loading" | "ready" | "error";

function weightMessageFor(error: unknown): string {
  return error instanceof WeightApiError
    ? error.message
    : "Could not load your weight trend. Please try again.";
}

// ─────────────────────────────────────────────────────────────────────────────
// Visual-review sub-state seam (FTY-265)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Registers the `weight.sheet` sub-state preset with the FTY-247 visual-review
 * registry from this weight-owned module — not the shared registry/manifest
 * files (`e2e/visualReview/registry.ts` / `presets.ts`). The weight-log sheet
 * sits behind `sheetVisible`, a press-only sub-state (see below), so it is one
 * of the "deferred sub-state presets" the FTY-247 README calls out as needing a
 * screen-owned seam. Registration is a plain map insert with no secrets and no
 * auth state (see `e2e/visualReview/types.ts`), so it runs unconditionally at
 * module load, same as the in-scope presets in `e2e/visualReview/presets.ts`;
 * only *activating* it reaches a real screen, and only through the
 * `isE2EMode()`-gated deep-link route.
 */
registerVisualReviewPreset({
  name: "weight.sheet",
  route: "/trends",
  settledPath: "/trends",
});

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────

interface TrendsScreenProps {
  session?: Session;
  unitsPreference?: UnitsPreference;
  /**
   * Injectable for tests; falls back to the live session-scoped value
   * (state/goalDirection.tsx), which the provider hydrates from the authoritative
   * `GET /goal` read on launch and Settings/Onboarding refresh on a goal save. It
   * is `null`/unknown only when no goal can be read (offline, or none set), which
   * reads as a neutral delta (no toward/away claim).
   */
  goalDirection?: GoalDirection;
  /** Clock, re-read at each focus gain (FTY-365). Injectable for tests. */
  now?: () => Date;
  /** Foreground+focus signal (FTY-365). Injectable for tests. */
  useActive?: () => boolean;
  /** Injectable for tests. */
  listWeightEntries?: typeof listWeightEntriesApi;
  /** Injectable for tests. */
  getDailySummaryRange?: typeof getDailySummaryRangeApi;
  /** Injectable for tests. */
  createWeightEntry?: typeof createWeightEntryApi;
  /** Injectable for tests. */
  store?: CadenceStore;
  /** Injectable for tests. */
  notifications?: NotificationsAdapter;
  /** Called when a day cell is tapped; parent handles navigation. */
  onDayPress?: (date: string) => void;
  /** Called when the gear / profile icon in the header is pressed. */
  onPressProfile?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// TrendsScreen
// ─────────────────────────────────────────────────────────────────────────────

export function TrendsScreen({
  session: sessionOverride,
  unitsPreference = "metric",
  goalDirection: goalDirectionOverride,
  now = () => new Date(),
  useActive = useScreenActive,
  listWeightEntries = listWeightEntriesApi,
  getDailySummaryRange = getDailySummaryRangeApi,
  createWeightEntry = createWeightEntryApi,
  store,
  notifications,
  onDayPress,
  onPressProfile,
}: TrendsScreenProps = {}) {
  const liveSession = useSession();
  const session: Session =
    sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession: ApiSession | null = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

  // The goal direction, or `null` when unknown. The provider hydrates it from the
  // authoritative `GET /goal` read on launch (and Settings/Onboarding refresh it on
  // a goal save), so a returning user's existing goal is known after a cold launch.
  // `resolveDeltaGoalState` treats `null` as neutral so a user whose goal can't be
  // read is never mis-colored "away" by a guessed default (state/goalDirection.tsx).
  const liveGoalDirection = useGoalDirection();
  const goalDirection: GoalDirection | null =
    goalDirectionOverride ?? liveGoalDirection ?? null;

  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  // Focus refresh (FTY-365): the tab stays mounted across switches, so the
  // read effects below also key on `focusSeq` — one silent refetch per focus
  // gain — and the date window derives from `focusNow`, the clock re-read at
  // each focus, so it rolls across midnight while the app stays open.
  const isActive = useActive();
  const { focusNow, focusSeq } = useFocusRefresh(isActive, now);

  const todayStr = useMemo(() => formatDate(focusNow), [focusNow]);

  // ── Range ────────────────────────────────────────────────────────────────
  const [range, setRange] = useState<DateRangeKey>(DEFAULT_DATE_RANGE);
  const { from, to } = useMemo(
    () => rangeBounds(range, focusNow),
    [range, focusNow],
  );
  const allDates = useMemo(() => buildDayRange(from, to), [from, to]);

  // ── Weight entries ────────────────────────────────────────────────────────
  const [entries, setEntries] = useState<readonly WeightEntryDTO[]>([]);
  const [weightPhase, setWeightPhase] = useState<LoadPhase>("loading");
  const [weightError, setWeightError] = useState<string | null>(null);
  const [weightReload, setWeightReload] = useState(0);
  const [chartWidth, setChartWidth] = useState(0);

  const reloadWeight = useCallback(() => {
    setWeightPhase("loading");
    setWeightReload((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!apiSession) return;
    let active = true;
    listWeightEntries(apiSession, from, to).then(
      (loaded) => {
        if (!active) return;
        setEntries(loaded);
        setWeightError(null);
        setWeightPhase("ready");
      },
      (err: unknown) => {
        if (!active) return;
        setWeightError(weightMessageFor(err));
        setWeightPhase("error");
      },
    );
    return () => {
      active = false;
    };
    // `focusSeq` refetches on each focus gain (FTY-365) without touching
    // `weightPhase`, so the chart keeps its data until fresh entries replace
    // it in place — only `reloadWeight` (the user retry) shows loading.
  }, [apiSession, listWeightEntries, from, to, weightReload, focusSeq]);

  // ── EWMA + headline ───────────────────────────────────────────────────────
  const ewmaKg = useMemo(() => computeEWMAFromEntries(entries), [entries]);
  const headline = useMemo(
    () => computeHeadlineDelta(ewmaKg, unitsPreference),
    [ewmaKg, unitsPreference],
  );
  // Goal-aware, not "down = good" (ux-design §4b, FTY-189).
  const deltaGoalState = useMemo(
    () => (headline ? resolveDeltaGoalState(headline.direction, goalDirection) : "neutral"),
    [headline, goalDirection],
  );

  // ── Adherence summaries ──────────────────────────────────────────────────
  const [adherenceError, setAdherenceError] = useState<string | null>(null);
  const [rawSummaries, setRawSummaries] = useState<
    readonly (DailySummaryDTO | null)[]
  >([]);
  const [adherenceReload, setAdherenceReload] = useState(0);
  // The settled phase is keyed to the read that produced it. A new read for a
  // *different* content selection — initial mount, a range change, or a retry
  // from the error state — has a fresh key with no same-range ready content to
  // stand in, so the card derives back to `loading` instead of leaving the
  // previous content on screen while the new read is in flight (FTY-188). A
  // same-range refresh (a focus gain, or the post-weight-save reload) instead
  // keeps the settled ready content visible until fresh data replaces it in
  // place — never an unmount-to-skeleton swap (FTY-365, calm-by-default).
  const adherenceRequestKey = `${from}|${to}|${adherenceReload}|${focusSeq}`;
  const [adherenceSettled, setAdherenceSettled] = useState<{
    key: string;
    range: DateRangeKey;
    phase: "ready" | "error";
  } | null>(null);
  const adherencePhase: LoadPhase =
    adherenceSettled?.key === adherenceRequestKey
      ? adherenceSettled.phase
      : adherenceSettled?.phase === "ready" && adherenceSettled.range === range
        ? "ready"
        : "loading";

  const reloadAdherence = useCallback(() => {
    setAdherenceError(null);
    setAdherenceReload((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!apiSession) return;
    let active = true;

    const sessionForDaily: DailySummarySession = {
      baseUrl: apiSession.baseUrl,
      token: apiSession.token,
      userId: apiSession.userId,
    };

    // One range read for the whole window — never one request per day.
    getDailySummaryRange(sessionForDaily, from, to)
      .then((results) => {
        if (!active) return;
        setRawSummaries(results);
        setAdherenceError(null);
        setAdherenceSettled({ key: adherenceRequestKey, range, phase: "ready" });
      })
      .catch((err: unknown) => {
        if (!active) return;
        setRawSummaries([]);
        setAdherenceError(
          err instanceof DailySummaryApiError
            ? err.message
            : "Could not load your intake history. Please try again.",
        );
        setAdherenceSettled({ key: adherenceRequestKey, range, phase: "error" });
      });

    return () => {
      active = false;
    };
  }, [
    apiSession,
    getDailySummaryRange,
    from,
    to,
    range,
    adherenceReload,
    adherenceRequestKey,
    focusSeq,
  ]);

  const adherence: AdherenceSummary = useMemo(
    () => computeAdherence(rawSummaries, allDates),
    [rawSummaries, allDates],
  );
  // Once the read settles, which honest content state to show: real data, an
  // uncounted-only range ("N entries awaiting details"), or a genuine empty
  // (ux-design §Acknowledge-every-action; FTY-188).
  const contentState = useMemo(
    () => adherenceContentState(adherence),
    [adherence],
  );

  // ── Log weight sheet ───────────────────────────────────────────────────────
  // E2E-only initial-state seam (FTY-265): the sheet is normally opened only by
  // the "+ Log weight" press below. When the `weight.sheet` visual-review preset
  // is the one active at mount, the sheet instead opens immediately — a real
  // reachable state, not a scripted tap — so the FTY-238 weight audit can
  // screenshot it. Read once, lazily: the whole navigator subtree remounts on
  // every preset activation (app/_layout.tsx keys on the revision), so a
  // freshly-mounted TrendsScreen always reflects the currently active preset.
  // `isE2EMode()` gates the read so a release build never opens the sheet on
  // mount, regardless of this module's registered preset state.
  const activeVisualReviewPreset = useVisualReviewCore().presetName;
  const [sheetVisible, setSheetVisible] = useState(
    () => isE2EMode() && activeVisualReviewPreset === "weight.sheet",
  );
  // The settled marker for this preset (see WeightLogSheet's settledMarkerTestID
  // doc): only set once the weight-entries read has resolved, so screenshot
  // automation never captures the sheet before its seeded data has settled.
  // Undefined whenever this preset isn't the active one, so a normal "+ Log
  // weight" open never renders it.
  const weightSheetSettledMarker =
    isE2EMode() && activeVisualReviewPreset === "weight.sheet" && weightPhase === "ready"
      ? "visual-review-settled:weight.sheet"
      : undefined;
  const lastEntry: WeightEntryDTO | null =
    entries.length > 0 ? entries[entries.length - 1]! : null;

  const handleWeightSaved = useCallback(
    (date: string) => {
      reloadWeight();
      reloadAdherence();
      if (store && notifications) {
        void onWeightLogged(date, store, notifications);
      }
    },
    [reloadWeight, reloadAdherence, store, notifications],
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Sign-in required
  // ─────────────────────────────────────────────────────────────────────────

  if (!session) {
    return (
      <View
        style={[
          styles.center,
          { backgroundColor: colors.surface, paddingTop: insets.top + 24 },
        ]}
      >
        <Text style={[styles.centerTitle, { color: colors.text }]}>
          Sign in to view your trends
        </Text>
        <Text style={[styles.centerBody, { color: colors.textSecondary }]}>
          Your weight trend and intake history are stored privately on your
          account.
        </Text>
      </View>
    );
  }

  return (
    <>
      <View style={[styles.screen, { backgroundColor: colors.surface }]}>
        <ScrollView
          testID="trends-screen"
          style={styles.scroll}
          contentContainerStyle={[
            styles.content,
            {
              // Reserve at least the floating switcher's own footprint (FTY-242)
              // so the last card scrolls clear of the pill and the home indicator,
              // not a hand-derived tab-bar-era height (FTY-258).
              paddingBottom: floatingSwitcherClearance(insets.bottom),
            },
          ]}
        >
          <ScreenHeader
            title="Trends"
            actions={
              onPressProfile ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Open profile"
                  accessibilityHint="Opens profile and settings"
                  onPress={onPressProfile}
                  style={styles.headerAction}
                >
                  <AppIcon name="gear" size={22} color={colors.text} />
                </Pressable>
              ) : null
            }
          />

          {/* Headline delta */}
          {headline ? (
            <View
              style={styles.headlineRow}
              accessibilityLabel={`Current weight trend: ${headline.current} ${headline.unit}, ${headline.direction === "↑" ? "up" : headline.direction === "↓" ? "down" : "stable"} ${Math.abs(headline.delta)} ${headline.unit} ${rangeProse(range)}${
                deltaGoalState === "toward"
                  ? ", toward your goal"
                  : deltaGoalState === "away"
                    ? ", away from your goal"
                    : ""
              }`}
            >
              <ThemedNumber
                value={`${headline.current} ${headline.unit}`}
                scale="title1"
              />
              <Text
                style={[
                  styles.headlineDelta,
                  {
                    // Goal-aware: keyed off progress toward the user's goal
                    // direction, not "down = good" (ux-design §4b, FTY-189).
                    // `accentText` (not `accent`) is the AA-safe token for text.
                    color:
                      deltaGoalState === "toward"
                        ? colors.accentText
                        : deltaGoalState === "away"
                          ? colors.coral
                          : colors.textSecondary,
                  },
                ]}
              >
                {` ${headline.direction}${Math.abs(headline.delta)} ${rangeProse(range)}`}
              </Text>
            </View>
          ) : null}

          {/* Range selector */}
          <RangeSelector
            selected={range}
            onChange={(r) => {
              setRange(r);
            }}
          />

          {/* Weight card */}
          <View
            style={[
              styles.card,
              { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
            ]}
            onLayout={(e) => setChartWidth(e.nativeEvent.layout.width - spacing.base * 2)}
          >
            <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
              WEIGHT TREND
            </Text>
            <EWMATrendChart
              entries={entries}
              ewmaKg={ewmaKg}
              unitsPreference={unitsPreference}
              loading={weightPhase === "loading"}
              error={weightPhase === "error" ? weightError : null}
              onRetry={reloadWeight}
              today={todayStr}
              width={chartWidth}
            />
            <Pressable
              testID="log-weight-btn"
              accessibilityRole="button"
              accessibilityLabel="Log weight"
              onPress={() => setSheetVisible(true)}
              style={styles.logWeightBtn}
            >
              <Text style={[styles.logWeightLabel, { color: colors.accentText }]}>
                + Log weight
              </Text>
            </Pressable>
          </View>

          {/* Adherence card */}
          <View
            style={[
              styles.card,
              { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
            ]}
          >
            <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
              INTAKE ADHERENCE
            </Text>

            {adherencePhase === "loading" ? (
              // In-place skeleton placeholder. It always resolves: the range
              // effect drives `adherencePhase` to `ready`/`error`, so this is
              // never a permanent placeholder (FTY-188). Skeleton honors Reduce
              // Motion, degrading to a static block.
              <View
                testID="adherence-loading"
                accessibilityRole="progressbar"
                accessibilityLabel="Loading intake adherence"
                style={styles.adherenceLoading}
              >
                <Skeleton width={168} height={18} borderRadius={6} />
                <Skeleton width={132} height={18} borderRadius={6} />
              </View>
            ) : adherencePhase === "error" ? (
              <View
                accessibilityRole="alert"
                accessibilityLabel="Intake adherence failed to load"
                style={styles.errorBox}
              >
                <Text style={[styles.errorText, { color: colors.textSecondary }]}>
                  {adherenceError ?? "Could not load your intake history. Please try again."}
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Try again"
                  onPress={reloadAdherence}
                  style={[styles.retryBtn, { borderRadius: radius.md }]}
                >
                  <Text style={[styles.retryLabel, { color: colors.accentText }]}>
                    Try again
                  </Text>
                </Pressable>
              </View>
            ) : contentState === "uncounted" ? (
              <AdherenceUncountedRow
                count={adherence.uncountedEntries}
                colors={colors}
              />
            ) : contentState === "empty" ? (
              <AdherenceEmptyInvite colors={colors} />
            ) : (
              <>
                <AdherenceSummaryRow
                  adherence={adherence}
                  colors={colors}
                />
                <AdherenceStrip
                  days={adherence.days}
                  today={todayStr}
                  onDayPress={onDayPress}
                />
              </>
            )}
          </View>
        </ScrollView>

        {/* Opaque status-bar backdrop (FTY-261): ScreenHeader scrolls away with
            the body, so this sibling pins the top safe-area inset above the
            ScrollView to keep scrolled content off the status bar. */}
        <View
          testID="trends-status-bar-backdrop"
          pointerEvents="none"
          style={[
            styles.statusBarBackdrop,
            { height: insets.top, backgroundColor: colors.surface },
          ]}
        />
      </View>

      {/* Weight log sheet */}
      {apiSession ? (
        <WeightLogSheet
          visible={sheetVisible}
          onClose={() => setSheetVisible(false)}
          onSaved={handleWeightSaved}
          session={apiSession}
          unitsPreference={unitsPreference}
          lastEntry={lastEntry}
          today={todayStr}
          create={createWeightEntry}
          settledMarkerTestID={weightSheetSettledMarker}
        />
      ) : null}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function RangeSelector({
  selected,
  onChange,
}: {
  selected: DateRangeKey;
  onChange: (r: DateRangeKey) => void;
}) {
  return (
    <View style={styles.rangeRow}>
      <SegmentedControl<DateRangeKey>
        testID="trends-range-selector"
        options={DATE_RANGE_OPTIONS.map((opt) => ({
          value: opt.key,
          label: opt.label,
        }))}
        selected={selected}
        onSelect={onChange}
        accessibilityLabel="Date range selector"
      />
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  screen: { flex: 1 },
  scroll: { flex: 1 },
  content: { paddingHorizontal: spacing.base, gap: spacing.base },
  statusBarBackdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
  },

  center: { flex: 1, paddingHorizontal: 24, alignItems: "center" },
  centerTitle: {
    fontSize: typeScale.title2,
    fontWeight: "700",
    textAlign: "center",
  },
  centerBody: {
    fontSize: typeScale.body,
    textAlign: "center",
    marginTop: spacing.md,
  },

  headerAction: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },

  headlineRow: {
    flexDirection: "row",
    alignItems: "baseline",
    flexWrap: "wrap",
    marginBottom: spacing.xs,
  },
  headlineDelta: {
    fontSize: typeScale.callout,
    fontWeight: "500",
    marginLeft: 4,
  },

  rangeRow: {
    marginBottom: spacing.xs,
  },

  card: {
    padding: spacing.base,
    gap: spacing.md,
  },
  sectionLabel: {
    fontSize: typeScale.caption1,
    fontWeight: "600",
    letterSpacing: 0.5,
  },

  logWeightBtn: {
    alignSelf: "flex-end",
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    minHeight: 44,
    minWidth: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  logWeightLabel: { fontSize: typeScale.subhead, fontWeight: "600" },

  adherenceLoading: { gap: spacing.xs },

  errorBox: { gap: spacing.sm },
  errorText: { fontSize: typeScale.body },
  retryBtn: {
    paddingVertical: spacing.sm,
    alignItems: "center",
    minHeight: 44,
  },
  retryLabel: { fontSize: typeScale.callout, fontWeight: "600" },
});
