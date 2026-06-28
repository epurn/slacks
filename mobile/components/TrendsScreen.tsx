/**
 * Trends screen for FTY-101. Rebuilt against the FTY-097 design system.
 *
 * Layout (§4b): weight outcome up top, intake behaviour beneath it. The EWMA
 * smoothed trend line — not any single reading — is the visual lead.
 *
 * Five features:
 *   1. Smoothed weight-trend line (EWMA) over raw daily points with range selector
 *      and headline delta.
 *   2. Intake-adherence summary (avg kcal vs. target, days-on-target, strip).
 *   3. Past-day drilldown — tapping a day opens that day's timeline.
 *   4. "Log weight" sheet — opens a numeric entry, seeded with the last value.
 *   5. Weigh-in reminder — cadence preference + due-only local notification.
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
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  listWeightEntries as listWeightEntriesApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import {
  getDailySummaryRange as getDailySummaryRangeApi,
  type DailySummaryDTO,
  type DailySummarySession,
} from "@/api/dailySummary";
import { AdherenceStrip } from "@/components/AdherenceStrip";
import { EWMATrendChart } from "@/components/EWMATrendChart";
import { WeightLogSheet } from "@/components/WeightLogSheet";
import type { UnitsPreference } from "@/state/profile";
import { useSession, toApiSession, type Session, type ApiSession } from "@/state/session";
import { formatDate } from "@/state/weightEntries";
import {
  DEFAULT_DATE_RANGE,
  DATE_RANGE_OPTIONS,
  computeEWMAFromEntries,
  computeHeadlineDelta,
  computeAdherence,
  rangeBounds,
  buildDayRange,
  type DateRangeKey,
  type AdherenceSummary,
} from "@/state/trends";
import {
  DEFAULT_CADENCE,
  CADENCE_OPTIONS,
  applyReminderSettings,
  onWeightLogged,
  type WeighInCadence,
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
}

// ─────────────────────────────────────────────────────────────────────────────
// TrendsScreen
// ─────────────────────────────────────────────────────────────────────────────

export function TrendsScreen({
  session: sessionOverride,
  unitsPreference = "metric",
  now = new Date(),
  listWeightEntries = listWeightEntriesApi,
  getDailySummaryRange = getDailySummaryRangeApi,
  createWeightEntry = createWeightEntryApi,
  store,
  notifications,
  onDayPress,
}: TrendsScreenProps = {}) {
  const liveSession = useSession();
  const session: Session =
    sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession: ApiSession | null = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

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

  // ── Adherence summaries ──────────────────────────────────────────────────
  const [adherencePhase, setAdherencePhase] = useState<LoadPhase>("loading");
  const [rawSummaries, setRawSummaries] = useState<
    readonly (DailySummaryDTO | null)[]
  >([]);
  const [adherenceReload, setAdherenceReload] = useState(0);

  const reloadAdherence = useCallback(() => {
    setAdherencePhase("loading");
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
        setAdherencePhase("ready");
      })
      .catch(() => {
        if (!active) return;
        setRawSummaries([]);
        setAdherencePhase("ready");
      });

    return () => {
      active = false;
    };
  }, [apiSession, getDailySummaryRange, from, to, adherenceReload]);

  const adherence: AdherenceSummary = useMemo(
    () => computeAdherence(rawSummaries, allDates),
    [rawSummaries, allDates],
  );

  // ── Cadence ───────────────────────────────────────────────────────────────
  const [cadence, setCadenceState] = useState<WeighInCadence>(DEFAULT_CADENCE);

  useEffect(() => {
    if (!store) return;
    store.getCadence().then((c) => {
      if (c) setCadenceState(c);
    });
  }, [store]);

  const handleCadenceChange = useCallback(
    (newCadence: WeighInCadence) => {
      setCadenceState(newCadence);
      if (store && notifications) {
        const lastDate = entries.length > 0 ? entries[entries.length - 1]!.effective_date : null;
        void applyReminderSettings(newCadence, lastDate, store, notifications);
      }
    },
    [store, notifications, entries],
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
      <ScrollView
        style={[styles.screen, { backgroundColor: colors.surface }]}
        contentContainerStyle={[
          styles.content,
          {
            paddingTop: insets.top + spacing.sm,
            paddingBottom: insets.bottom + 80 + spacing.xl,
          },
        ]}
      >
        {/* Page title */}
        <Text
          style={[styles.pageTitle, { color: colors.text }]}
          accessibilityRole="header"
        >
          Trends
        </Text>

        {/* Headline delta */}
        {headline ? (
          <View
            style={styles.headlineRow}
            accessibilityLabel={`Current weight trend: ${headline.current} ${headline.unit}, ${headline.direction === "↑" ? "up" : headline.direction === "↓" ? "down" : "stable"} ${Math.abs(headline.delta)} ${headline.unit} this ${range === "1M" ? "month" : range === "3M" ? "three months" : "six months"}`}
          >
            <Text style={[styles.headlineValue, { color: colors.text }]}>
              {`${headline.current} ${headline.unit}`}
            </Text>
            <Text
              style={[
                styles.headlineDelta,
                {
                  color:
                    headline.direction === "↓"
                      ? colors.accent
                      : headline.direction === "↑"
                        ? colors.coral
                        : colors.textSecondary,
                },
              ]}
            >
              {` ${headline.direction}${Math.abs(headline.delta)} this ${range === "1M" ? "month" : range}`}
            </Text>
          </View>
        ) : null}

        {/* Range selector */}
        <RangeSelector
          selected={range}
          onChange={(r) => {
            setRange(r);
          }}
          colors={colors}
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
            width={chartWidth}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Log weight"
            onPress={() => setSheetVisible(true)}
            style={[
              styles.logWeightBtn,
              { backgroundColor: colors.accent, borderRadius: radius.md },
            ]}
          >
            <Text style={[styles.logWeightLabel, { color: colors.accentForeground }]}>
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
            <Text style={[styles.loadingText, { color: colors.textSecondary }]}>
              Loading...
            </Text>
          ) : (
            <>
              <AdherenceSummaryRow
                adherence={adherence}
                colors={colors}
              />
              <AdherenceStrip
                days={adherence.days}
                onDayPress={onDayPress}
              />
            </>
          )}
        </View>

        {/* Reminder settings card */}
        <View
          style={[
            styles.card,
            { backgroundColor: colors.surfaceRaised, borderRadius: radius.lg },
          ]}
        >
          <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
            WEIGH-IN REMINDER
          </Text>
          <CadencePicker
            selected={cadence}
            onChange={handleCadenceChange}
            colors={colors}
          />
        </View>
      </ScrollView>

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
  colors,
}: {
  selected: DateRangeKey;
  onChange: (r: DateRangeKey) => void;
  colors: { text: string; accent: string; controlBackground: string; surfaceRaised: string };
}) {
  return (
    <View
      style={styles.rangeRow}
      accessibilityRole="toolbar"
      accessibilityLabel="Date range selector"
    >
      {DATE_RANGE_OPTIONS.map((opt) => {
        const isSelected = opt.key === selected;
        return (
          <Pressable
            key={opt.key}
            testID={`range-btn-${opt.key}`}
            accessibilityRole="button"
            accessibilityLabel={`${opt.label} range`}
            accessibilityState={{ selected: isSelected }}
            onPress={() => onChange(opt.key)}
            style={[
              styles.rangeBtn,
              {
                backgroundColor: isSelected
                  ? colors.accent
                  : colors.controlBackground,
                borderRadius: radius.md,
              },
            ]}
          >
            <Text
              style={[
                styles.rangeBtnLabel,
                { color: isSelected ? colors.text : colors.text },
              ]}
            >
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
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
  if (adherence.avgCalories === null && adherence.daysWithTarget === 0) {
    return (
      <Text style={[styles.emptyText, { color: colors.textSecondary }]}>
        No intake data for this range.
      </Text>
    );
  }

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

function CadencePicker({
  selected,
  onChange,
  colors,
}: {
  selected: WeighInCadence;
  onChange: (c: WeighInCadence) => void;
  colors: {
    text: string;
    textSecondary: string;
    accent: string;
    controlBackground: string;
    separator: string;
  };
}) {
  return (
    <View style={styles.cadenceList}>
      {CADENCE_OPTIONS.map((opt, i) => {
        const isSelected = opt.value === selected;
        return (
          <Pressable
            key={opt.value}
            testID={`cadence-option-${opt.value}`}
            accessibilityRole="radio"
            accessibilityLabel={opt.label}
            accessibilityState={{ checked: isSelected }}
            onPress={() => onChange(opt.value)}
            style={[
              styles.cadenceOption,
              i < CADENCE_OPTIONS.length - 1
                ? { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.separator }
                : undefined,
            ]}
          >
            <Text style={[styles.cadenceLabel, { color: colors.text }]}>
              {opt.label}
            </Text>
            {isSelected ? (
              <Text style={[styles.checkmark, { color: colors.accent }]}>✓</Text>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingHorizontal: spacing.base, gap: spacing.base },

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

  pageTitle: {
    fontSize: typeScale.largeTitle,
    fontWeight: "700",
    marginBottom: spacing.xs,
  },

  headlineRow: {
    flexDirection: "row",
    alignItems: "baseline",
    flexWrap: "wrap",
    marginBottom: spacing.xs,
  },
  headlineValue: {
    fontSize: typeScale.title1,
    fontWeight: "700",
  },
  headlineDelta: {
    fontSize: typeScale.callout,
    fontWeight: "500",
    marginLeft: 4,
  },

  rangeRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  rangeBtn: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.base,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  rangeBtnLabel: { fontSize: typeScale.subhead, fontWeight: "600" },

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
    paddingVertical: spacing.md,
    alignItems: "center",
    minHeight: 44,
  },
  logWeightLabel: { fontSize: typeScale.callout, fontWeight: "600" },

  loadingText: { fontSize: typeScale.body },
  emptyText: { fontSize: typeScale.body },

  adherenceRow: { gap: spacing.xs },
  adherenceStat: { fontSize: typeScale.subhead },

  cadenceList: { gap: 0 },
  cadenceOption: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.md,
    minHeight: 44,
  },
  cadenceLabel: { fontSize: typeScale.body },
  checkmark: { fontSize: typeScale.body, fontWeight: "700" },
});
