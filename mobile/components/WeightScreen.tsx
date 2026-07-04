import { useCallback, useEffect, useMemo, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  WeightApiError,
  createWeightEntry as createWeightEntryApi,
  listWeightEntries as listWeightEntriesApi,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";
import { typeScale } from "@/theme";
import { DisplayText } from "@/components/ui";
import { WeightEntryInput } from "@/components/WeightEntryInput";
import { WeightTrendChart } from "@/components/WeightTrendChart";
import type { UnitsPreference } from "@/state/profile";
import { useSession, toApiSession, type Session } from "@/state/session";
import { formatDate, subtractDays } from "@/state/weightEntries";

/** Days of history to show in the trend chart. */
const TREND_DAYS = 90;

type LoadPhase = "loading" | "ready" | "error";

function messageFor(error: unknown): string {
  return error instanceof WeightApiError
    ? error.message
    : "Something went wrong. Please try again.";
}

/**
 * Weight logging and trend screen for FTY-074. Loads the authenticated user's
 * weight entries for the past 90 days from FTY-070, renders a simple trend
 * chart, and lets the user log a new entry via the weight input.
 *
 * After a successful entry the chart re-fetches so the new point appears.
 * Until the sign-in flow lands (separate story), there is no session and a
 * clear sign-in message is shown — mirroring the TodayScreen pattern.
 *
 * Privacy: weight values are never written to logs or error messages here.
 * `session`, `create`, `load`, and `now` are injectable for tests.
 */
export function WeightScreen({
  session: sessionOverride,
  unitsPreference = "metric",
  create = createWeightEntryApi,
  load = listWeightEntriesApi,
  now = new Date(),
}: {
  session?: Session;
  unitsPreference?: UnitsPreference;
  create?: typeof createWeightEntryApi;
  load?: typeof listWeightEntriesApi;
  now?: Date;
} = {}) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );
  const insets = useSafeAreaInsets();
  const [chartWidth, setChartWidth] = useState(0);

  const todayStr = useMemo(() => formatDate(now), [now]);
  const fromStr = useMemo(() => formatDate(subtractDays(now, TREND_DAYS)), [now]);

  const [entries, setEntries] = useState<readonly WeightEntryDTO[]>([]);
  const [loadPhase, setLoadPhase] = useState<LoadPhase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Trigger a re-fetch while resetting to loading state — called from handlers,
  // not from inside the effect (avoids the cascading-render lint rule).
  const reload = useCallback(() => {
    setLoadPhase("loading");
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (!apiSession) return;
    let active = true;
    load(apiSession, fromStr, todayStr).then(
      (loaded) => {
        if (!active) return;
        setEntries(loaded);
        setLoadError(null);
        setLoadPhase("ready");
      },
      (error: unknown) => {
        if (!active) return;
        setLoadError(messageFor(error));
        setLoadPhase("error");
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, load, fromStr, todayStr, reloadKey]);

  const handleSubmit = useCallback(
    async (weight: number) => {
      if (!apiSession || submitting) return;
      setSubmitting(true);
      setSubmitError(null);
      try {
        await create(apiSession, weight, todayStr);
        reload();
      } catch (error) {
        setSubmitError(messageFor(error));
      } finally {
        setSubmitting(false);
      }
    },
    [apiSession, submitting, create, todayStr, reload],
  );

  if (!session) {
    return <SignInRequired insetTop={insets.top + 24} colors={colors} />;
  }

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 24 },
      ]}
    >
      <DisplayText scale="largeTitle" accessibilityRole="header">
        Weight
      </DisplayText>

      <View style={styles.card}>
        <Text style={styles.sectionLabel}>Log weight</Text>
        <WeightEntryInput
          unitsPreference={unitsPreference}
          submitting={submitting}
          submitError={submitError}
          onSubmit={(weight) => void handleSubmit(weight)}
        />
      </View>

      <View
        style={styles.card}
        onLayout={(e) => setChartWidth(e.nativeEvent.layout.width)}
      >
        <Text style={styles.sectionLabel}>
          Trend (last {TREND_DAYS} days)
        </Text>
        <WeightTrendChart
          entries={entries}
          unitsPreference={unitsPreference}
          loading={loadPhase === "loading"}
          error={loadPhase === "error" ? loadError : null}
          onRetry={reload}
          width={chartWidth}
        />
      </View>
    </ScrollView>
  );
}

function SignInRequired({ insetTop, colors }: { insetTop: number; colors: ColorPalette }) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={[styles.center, { paddingTop: insetTop }]}>
      <DisplayText
        scale="title2Large"
        style={styles.centerTitle}
        accessibilityRole="header"
      >
        Sign in to log your weight
      </DisplayText>
      <Text style={styles.centerBody}>
        Your weight log is stored privately against your account. Sign in to
        log and view your weight trend.
      </Text>
    </View>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    screen: {
      flex: 1,
      backgroundColor: colors.surface,
    },
    content: {
      paddingHorizontal: 16,
      gap: 16,
    },
    card: {
      backgroundColor: colors.surfaceRaised,
      borderRadius: 12,
      padding: 16,
      gap: 12,
    },
    sectionLabel: {
      fontSize: typeScale.footnote,
      fontWeight: "600",
      color: colors.textMuted,
      textTransform: "uppercase",
      letterSpacing: 0.5,
    },
    center: {
      flex: 1,
      backgroundColor: colors.surface,
      paddingHorizontal: 24,
      alignItems: "center",
    },
    centerTitle: {
      textAlign: "center",
    },
    centerBody: {
      fontSize: typeScale.subhead,
      color: colors.textMuted,
      textAlign: "center",
      marginTop: 12,
    },
  });
}
