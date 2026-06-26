import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  LogEventApiError,
  createLogEvent as createLogEventApi,
  listTodayLogEvents as listTodayLogEventsApi,
  type LogEventDTO,
} from "@/api/logEvents";
import { EntryRow } from "@/components/EntryRow";
import {
  POLL_INTERVAL_MS,
  hasPendingWork,
  useIntervalPolling,
} from "@/state/polling";
import { useSession, toApiSession, type Session } from "@/state/session";
import {
  OPTIMISTIC_ID_PREFIX,
  optimisticLogEvent,
  reconcileEvents,
  sortByNewest,
} from "@/state/today";
import { useScreenActive } from "@/state/useScreenActive";

/** Maximum raw-text length, mirrored from the FTY-030 contract. */
const MAX_RAW_TEXT_LENGTH = 2000;

type Phase = "loading" | "ready" | "error";

/** Map an API/network failure to a plain, nonjudgmental message. */
function messageFor(error: unknown, kind: "load" | "save"): string {
  if (error instanceof LogEventApiError) {
    return error.message;
  }
  return kind === "load"
    ? "We couldn't load your day. Check your connection and try again."
    : "We couldn't save that entry. Please try again.";
}

/**
 * The Today shell (FTY-031). Loads the authenticated user's real log events
 * from the FTY-030 list-today endpoint, renders them as a newest-first timeline
 * with accessible per-entry status, and lets the user submit natural-language
 * input that creates a new `pending` event — shown immediately (optimistically)
 * before the create round-trip resolves.
 *
 * Pending entries auto-refresh: while any visible event is non-terminal the
 * screen polls list-today on a fixed interval and reconciles the result, so a
 * `pending` entry reaches its terminal status without a manual refresh (FTY-032,
 * the ADR-0002 v1 mechanism). Polling stops when nothing is pending and pauses
 * when the screen is backgrounded or unfocused; a manual refresh is also kept.
 *
 * Until the mobile sign-in flow lands (a separate story) there is no session on
 * the device, so this renders a clear "sign in" state, mirroring the profile
 * capture flow. `load`/`create`/`session`/`useActive`/`pollIntervalMs` are
 * injectable for tests.
 */
export function TodayScreen({
  session: sessionOverride,
  load = listTodayLogEventsApi,
  create = createLogEventApi,
  useActive = useScreenActive,
  pollIntervalMs = POLL_INTERVAL_MS,
}: {
  session?: Session;
  load?: typeof listTodayLogEventsApi;
  create?: typeof createLogEventApi;
  useActive?: () => boolean;
  pollIntervalMs?: number;
} = {}) {
  const insets = useSafeAreaInsets();
  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

  const [events, setEvents] = useState<readonly LogEventDTO[]>([]);
  const [phase, setPhase] = useState<Phase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Monotonic counter for optimistic placeholder ids; never collides with a
  // server UUID and stays stable across renders.
  const tempId = useRef(0);

  // User-initiated refresh: show the loading state, then bump the reload key so
  // the fetch effect re-runs. Auto-refresh of pending entries is FTY-032.
  const refresh = useCallback(() => {
    setPhase("loading");
    setReloadKey((key) => key + 1);
  }, []);

  // Load the day's events. `setState` lives only in the promise callbacks (an
  // external-system update), never synchronously in the effect body.
  useEffect(() => {
    if (!apiSession) {
      return;
    }
    let active = true;
    load(apiSession).then(
      (loaded) => {
        if (!active) return;
        setEvents(sortByNewest(loaded));
        setLoadError(null);
        setPhase("ready");
      },
      (error) => {
        if (!active) return;
        setLoadError(messageFor(error, "load"));
        setPhase("error");
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, load, reloadKey]);

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || !apiSession || submitting) {
      return;
    }
    const id = `${OPTIMISTIC_ID_PREFIX}${tempId.current++}`;
    const optimistic = optimisticLogEvent({
      id,
      userId: apiSession.userId,
      rawText: trimmed,
      createdAt: new Date().toISOString(),
    });
    // Show the new entry immediately as pending, then reconcile with the server.
    setEvents((prev) => sortByNewest([optimistic, ...prev]));
    setText("");
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await create(apiSession, trimmed);
      setEvents((prev) =>
        sortByNewest(prev.map((event) => (event.id === id ? created : event))),
      );
    } catch (error) {
      // Roll back the optimistic entry and restore the input so nothing is lost.
      setEvents((prev) => prev.filter((event) => event.id !== id));
      setText(trimmed);
      setSubmitError(messageFor(error, "save"));
    } finally {
      setSubmitting(false);
    }
  }, [text, apiSession, submitting, create]);

  // One poll: refetch the day and reconcile into the timeline, preserving any
  // unacknowledged optimistic entry. Transient poll failures are swallowed so a
  // dropped request never replaces the visible timeline with an error — the
  // next tick retries, and the manual refresh surfaces persistent failures.
  const pollOnce = useCallback(() => {
    if (!apiSession) {
      return;
    }
    load(apiSession).then(
      (loaded) => {
        setEvents((prev) => reconcileEvents(prev, loaded));
      },
      () => {
        // Keep the current timeline; retry on the next interval.
      },
    );
  }, [apiSession, load]);

  // Poll while a non-terminal event is visible and the screen is active (the
  // app is foregrounded and this route is focused). Pausing during an in-flight
  // create lets that round-trip own the optimistic entry, avoiding a poll/create
  // race; polling resumes automatically once it settles if work remains.
  const isActive = useActive();
  const shouldPoll =
    phase === "ready" && isActive && !submitting && hasPendingWork(events);
  useIntervalPolling(shouldPoll, pollIntervalMs, pollOnce);

  if (!session) {
    return <SignInRequired insetTop={insets.top + 24} />;
  }

  const canSubmit = text.trim() !== "" && !submitting;

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 24 },
      ]}
      keyboardShouldPersistTaps="handled"
    >
      <View style={styles.header}>
        <Text style={styles.title} accessibilityRole="header">
          Today
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Refresh"
          accessibilityState={{ disabled: phase === "loading" }}
          disabled={phase === "loading"}
          onPress={() => void refresh()}
          style={styles.refresh}
        >
          <Text style={styles.refreshLabel}>Refresh</Text>
        </Pressable>
      </View>

      <View style={styles.composer}>
        <TextInput
          accessibilityLabel="Log food or exercise"
          placeholder="Add food or exercise…"
          placeholderTextColor="#A0A0A8"
          value={text}
          onChangeText={setText}
          multiline
          maxLength={MAX_RAW_TEXT_LENGTH}
          editable={!submitting}
          style={styles.input}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add entry"
          accessibilityState={{ disabled: !canSubmit }}
          disabled={!canSubmit}
          onPress={() => void handleSubmit()}
          style={[styles.add, !canSubmit && styles.addDisabled]}
        >
          <Text style={styles.addLabel}>{submitting ? "Adding…" : "Add"}</Text>
        </Pressable>
      </View>
      {submitError ? (
        <Text style={styles.error} accessibilityRole="alert">
          {submitError}
        </Text>
      ) : null}

      <Timeline
        events={events}
        phase={phase}
        loadError={loadError}
        onRetry={() => void refresh()}
      />
    </ScrollView>
  );
}

function Timeline({
  events,
  phase,
  loadError,
  onRetry,
}: {
  events: readonly LogEventDTO[];
  phase: Phase;
  loadError: string | null;
  onRetry: () => void;
}) {
  if (events.length === 0) {
    if (phase === "loading") {
      return (
        <View style={styles.state}>
          <ActivityIndicator accessibilityLabel="Loading your day" />
        </View>
      );
    }
    if (phase === "error") {
      return (
        <View style={styles.state}>
          <Text style={styles.stateText} accessibilityRole="alert">
            {loadError}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Try again"
            onPress={onRetry}
            style={styles.retry}
          >
            <Text style={styles.retryLabel}>Try again</Text>
          </Pressable>
        </View>
      );
    }
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          Nothing logged yet. Add your first food or exercise above.
        </Text>
      </View>
    );
  }

  return (
    <View>
      {phase === "error" && loadError ? (
        <Text style={styles.error} accessibilityRole="alert">
          {loadError}
        </Text>
      ) : null}
      <View style={styles.card}>
        {events.map((event) => (
          <EntryRow key={event.id} event={event} />
        ))}
      </View>
    </View>
  );
}

function SignInRequired({ insetTop }: { insetTop: number }) {
  return (
    <View style={[styles.center, { paddingTop: insetTop }]}>
      <Text style={styles.centerTitle} accessibilityRole="header">
        Sign in to see your day
      </Text>
      <Text style={styles.centerBody}>
        Your log is stored privately against your account. Sign in to add and
        review today&apos;s food and exercise.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#F2F2F7",
  },
  content: {
    paddingHorizontal: 16,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title: {
    fontSize: 34,
    fontWeight: "700",
    color: "#1C1C1E",
  },
  refresh: {
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  refreshLabel: {
    fontSize: 16,
    color: "#0A84FF",
    fontWeight: "500",
  },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    marginTop: 8,
    marginBottom: 16,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 17,
    color: "#1C1C1E",
  },
  add: {
    backgroundColor: "#0A84FF",
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  addDisabled: {
    backgroundColor: "#9DC9FF",
  },
  addLabel: {
    fontSize: 16,
    fontWeight: "600",
    color: "#FFFFFF",
  },
  error: {
    fontSize: 14,
    color: "#C0392B",
    marginBottom: 12,
    marginLeft: 4,
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: 12,
    overflow: "hidden",
  },
  state: {
    paddingVertical: 32,
    alignItems: "center",
    gap: 16,
  },
  stateText: {
    fontSize: 15,
    color: "#8E8E93",
    textAlign: "center",
    paddingHorizontal: 16,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 10,
    backgroundColor: "#E4E4EA",
  },
  retryLabel: {
    fontSize: 15,
    fontWeight: "600",
    color: "#1C1C1E",
  },
  center: {
    flex: 1,
    backgroundColor: "#F2F2F7",
    paddingHorizontal: 24,
    alignItems: "center",
  },
  centerTitle: {
    fontSize: 24,
    fontWeight: "700",
    color: "#1C1C1E",
    textAlign: "center",
  },
  centerBody: {
    fontSize: 15,
    color: "#8E8E93",
    textAlign: "center",
    marginTop: 12,
  },
});
