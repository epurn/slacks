/**
 * Past-day detail route: /day?date=YYYY-MM-DD
 *
 * Opens a historical date in the *same* timeline the Today screen renders — the
 * time-clustered rows (name · kcal · always-on source icon, ✎ edited), fed by the
 * item-forward entries-by-date read (FTY-198) for the selected date — with the
 * daily-summary hero above it, exactly as the Today layout does (design
 * §4b: "tapping a day opens that day's timeline — the Today layout for that
 * date"). The screen is read-only: past entries are viewed, not edited, so the
 * shared timeline is mounted in its `readOnly` mode (no correction/clarify/retry
 * affordances) — editing past entries is a separate concern (FTY-199 non-goal).
 *
 * The title is a prose date ("June 28" / "Today" / "Yesterday"), never a raw ISO
 * string (audit D4: human-format all user-facing dates), and that same prose is
 * the header's accessibility label.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  getDailySummary as getDailySummaryApi,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import type { DerivedItem } from "@/api/derivedItems";
import {
  listTodayLogEventEntries as listTodayLogEventEntriesApi,
  type LogEventEntryDTO,
} from "@/api/logEvents";
import { DailySummary } from "@/components/DailySummary";
import { Timeline } from "@/components/today/Timeline";
import { messageFor, type Phase } from "@/components/today/helpers";
import { type OutboxSyncState } from "@/state/outbox";
import { useSession, toApiSession, type Session } from "@/state/session";
import { sortByNewest } from "@/state/today";
import { formatDate, formatHumanDate } from "@/state/weightEntries";
import { useTheme, spacing, typeScale } from "@/theme";

// A past day never carries offline-queued captures or in-flight resolve
// animations, so the timeline's per-row state maps are always empty here. Stable
// module-level identities keep them from re-triggering renders.
const NO_OFFLINE_STATE: ReadonlyMap<string, OutboxSyncState> = new Map();
const NO_RESOLVE_ANIM: ReadonlySet<string> = new Set<string>();

export default function DayScreen({
  session: sessionOverride,
  loadEntries = listTodayLogEventEntriesApi,
  getDailySummary = getDailySummaryApi,
}: {
  /** Injectable session for tests (the route reads the live session otherwise). */
  session?: Session;
  /** Injectable entries-by-date read (FTY-198) for tests. */
  loadEntries?: typeof listTodayLogEventEntriesApi;
  /** Injectable daily-summary read for tests. */
  getDailySummary?: typeof getDailySummaryApi;
} = {}) {
  const { date } = useLocalSearchParams<{ date?: string }>();
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

  const [entries, setEntries] = useState<readonly LogEventEntryDTO[]>([]);
  const [phase, setPhase] = useState<Phase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DailySummaryDTO | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Load the day's entries in the item-forward Today-feed shape (FTY-198) so the
  // shared timeline renders each entry's resolved value rows for the selected
  // date. setState lives only in the promise callbacks (an external update).
  useEffect(() => {
    if (!apiSession || !date) return;
    let active = true;
    loadEntries(apiSession, date).then(
      (loaded) => {
        if (!active) return;
        setEntries(loaded);
        setLoadError(null);
        setPhase("ready");
      },
      (err: unknown) => {
        if (!active) return;
        setLoadError(messageFor(err, "load"));
        setPhase("error");
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, date, loadEntries, reloadKey]);

  // Load the daily summary for the same date to drive the hero above the
  // timeline (the Today layout), so the day's totals sit over its entries.
  useEffect(() => {
    if (!apiSession || !date) return;
    let active = true;
    getDailySummary(apiSession, date).then(
      (loaded) => {
        if (!active) return;
        setSummary(loaded);
        setSummaryError(null);
      },
      () => {
        if (!active) return;
        setSummaryError(
          "We couldn't load this day's summary. Check your connection and try again.",
        );
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, date, getDailySummary, reloadKey]);

  // Retry: show the loading state again, then bump the reload key so both fetch
  // effects re-run. Setting phase here (not inside the effect) keeps setState out
  // of the effect body per the project's cascading-render rule.
  const refresh = useCallback(() => {
    setPhase("loading");
    setLoadError(null);
    setReloadKey((key) => key + 1);
  }, []);

  const handleBack = useCallback(() => {
    router.back();
  }, [router]);

  // Fold the item-forward feed into the (events, itemsByEvent) shape the shared
  // timeline consumes: events newest-first, each event's derived rows keyed by id.
  const events = useMemo(
    () => sortByNewest(entries.map((entry) => entry.event)),
    [entries],
  );
  const itemsByEvent = useMemo(() => {
    const map: Record<string, readonly DerivedItem[]> = {};
    for (const entry of entries) {
      map[entry.event.id] = entry.items;
    }
    return map;
  }, [entries]);

  const title = date ? formatHumanDate(date, formatDate(new Date())) : "";

  return (
    <ScrollView
      testID="day-screen"
      style={[styles.screen, { backgroundColor: colors.surface }]}
      contentContainerStyle={[
        styles.content,
        {
          paddingTop: insets.top + spacing.base,
          paddingBottom: insets.bottom + spacing.xl,
        },
      ]}
    >
      {/* Header — prose date title, prose accessibility label (never raw ISO). */}
      <View style={styles.header}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={handleBack}
          style={styles.backBtn}
        >
          <Text style={[styles.backLabel, { color: colors.accentText }]}>‹ Trends</Text>
        </Pressable>
        <Text
          style={[styles.dateTitle, { color: colors.text }]}
          accessibilityRole="header"
          accessibilityLabel={title}
        >
          {title}
        </Text>
      </View>

      {/* Daily-summary hero above the timeline, as the Today layout does. */}
      <DailySummary summary={summary} error={summaryError} onRetry={refresh} />

      {/* The same clustered timeline as Today, read-only for a historical day. */}
      <Timeline
        events={events}
        itemsByEvent={itemsByEvent}
        offlineStateById={NO_OFFLINE_STATE}
        resolveAnimIds={NO_RESOLVE_ANIM}
        phase={phase}
        loadError={loadError}
        onRetry={refresh}
        readOnly
        emptyLabel="Nothing logged that day"
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingHorizontal: spacing.base, gap: spacing.base },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.base,
    marginBottom: spacing.sm,
  },
  backBtn: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  backLabel: { fontSize: typeScale.body, fontWeight: "500" },
  dateTitle: { fontSize: typeScale.title2, fontWeight: "700" },
});
