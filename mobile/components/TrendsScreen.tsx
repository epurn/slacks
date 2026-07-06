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
 * All injectable for tests: session, API functions, today date, cadence/
 * notification adapters.
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
// Registers the `trends.adherence_retry` visual-review preset (FTY-264) as a
// side effect, so the deep-link route can find it. See the module doc there —
// this import has no effect outside an active visual-review session.
import "@/components/trends/visualReviewPresets";
import { useGoalDirection } from "@/state/goalDirection";
import type { UnitsPreference } from "@/state/profile";
import { useSession, toApiSession, type Session, type ApiSession } from "@/state/session";
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
  now?: Date;
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
  now = new Date(),
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

  const todayStr = useMemo(() => formatDate(now), [now]);

  // ── Range ────────────────────────────────────────────────────────────────
  const [range, setRange] = useState<DateRangeKey>(DEFAULT_DATE_RANGE);
  const { from, to } = useMemo(
    () => rangeBounds(range, now),
    [range, now],
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
  }, [apiSession, listWeightEntries, from, to, weightReload]);

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
  // The settled phase is keyed to the read that produced it. Any new read —
  // initial mount, a range change, or a retry — has a fresh key, so the card
  // derives back to `loading` instead of leaving the previous ready/error
  // content on screen while the new read is in flight (FTY-188).
  const adherenceRequestKey = `${from}|${to}|${adherenceReload}`;
  const [adherenceSettled, setAdherenceSettled] = useState<{
    key: string;
    phase: "ready" | "error";
  } | null>(null);
  const adherencePhase: LoadPhase =
    adherenceSettled?.key === adherenceRequestKey
      ? adherenceSettled.phase
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
        setAdherenceSettled({ key: adherenceRequestKey, phase: "ready" });
      })
      .catch((err: unknown) => {
        if (!active) return;
        setRawSummaries([]);
        setAdherenceError(
          err instanceof DailySummaryApiError
            ? err.message
            : "Could not load your intake history. Please try again.",
        );
        setAdherenceSettled({ key: adherenceRequestKey, phase: "error" });
      });

    return () => {
      active = false;
    };
  }, [
    apiSession,
    getDailySummaryRange,
    from,
    to,
    adherenceReload,
    adherenceRequestKey,
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
  const [sheetVisible, setSheetVisible] = useState(false);
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

/**
 * The honest empty invite: genuinely nothing logged in the range. Distinct from
 * the uncounted state — here there are no entries at all, so we invite logging
 * rather than claim a false "no intake data" (FTY-188).
 */
function AdherenceEmptyInvite({
  colors,
}: {
  colors: { text: string; textSecondary: string; textMuted: string };
}) {
  return (
    <View
      style={styles.adherenceRow}
      accessible
      accessibilityLabel="No intake logged for this range"
    >
      <Text style={[styles.emptyTitle, { color: colors.text }]}>
        No meals logged in this range yet.
      </Text>
      <Text style={[styles.emptyText, { color: colors.textSecondary }]}>
        Your logged meals will show up here.
      </Text>
    </View>
  );
}

/**
 * The logged-but-uncounted state: entries exist in the range but none are
 * counted yet (they await a detail on Today). Never the false "No intake data"
 * — this acknowledges the real action and points at what to do next without
 * duplicating the Today clarify flow (ux-design §Acknowledge-every-action;
 * FTY-188).
 */
function AdherenceUncountedRow({
  count,
  colors,
}: {
  count: number;
  colors: { text: string; textSecondary: string; textMuted: string };
}) {
  const noun = count === 1 ? "entry" : "entries";
  return (
    <View
      style={styles.adherenceRow}
      accessible
      accessibilityLabel={`${count} ${noun} awaiting details`}
    >
      <Text style={[styles.emptyTitle, { color: colors.text }]}>
        {`${count} ${noun} awaiting details`}
      </Text>
      <Text style={[styles.emptyText, { color: colors.textSecondary }]}>
        Add their details on Today to count them toward your intake.
      </Text>
    </View>
  );
}

function AdherenceSummaryRow({
  adherence,
  colors,
}: {
  adherence: AdherenceSummary;
  colors: { text: string; textSecondary: string; textMuted: string };
}) {
  return (
    <View style={styles.adherenceRow}>
      {adherence.avgCalories !== null ? (
        <Text
          style={[styles.adherenceStat, { color: colors.text }]}
          accessibilityLabel={`Average: ${adherence.avgCalories} kcal per day`}
        >
          {`Avg ${adherence.avgCalories} kcal/day`}
        </Text>
      ) : null}
      {adherence.daysWithTarget > 0 ? (
        <Text
          style={[styles.adherenceStat, { color: colors.textSecondary }]}
          accessibilityLabel={`On target: ${adherence.daysOnTarget} of ${adherence.daysWithTarget} days`}
        >
          {`${adherence.daysOnTarget}/${adherence.daysWithTarget} days on target`}
        </Text>
      ) : null}
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
  emptyTitle: { fontSize: typeScale.body, fontWeight: "600" },
  emptyText: { fontSize: typeScale.body },

  adherenceRow: { gap: spacing.xs },
  adherenceStat: { fontSize: typeScale.subhead },

  errorBox: { gap: spacing.sm },
  errorText: { fontSize: typeScale.body },
  retryBtn: {
    paddingVertical: spacing.sm,
    alignItems: "center",
    minHeight: 44,
  },
  retryLabel: { fontSize: typeScale.callout, fontWeight: "600" },
});
