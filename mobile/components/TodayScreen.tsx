import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  editDerivedItem as editDerivedItemApi,
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import {
  getDailySummary as getDailySummaryApi,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import {
  uploadLabelImage as uploadLabelImageApi,
} from "@/api/labelCapture";
import {
  LogEventApiError,
  createLogEvent as createLogEventApi,
  listTodayLogEvents as listTodayLogEventsApi,
  type LogEventDTO,
} from "@/api/logEvents";
import {
  saveFood as saveFoodApi,
  searchSavedFoods as searchSavedFoodsApi,
  type SavedFoodDTO,
} from "@/api/savedFoods";
import { BarcodeScannerScreen } from "@/components/BarcodeScannerScreen";
import { DailySummary } from "@/components/DailySummary";
import { EntryRow } from "@/components/EntryRow";
import { LabelCaptureScreen } from "@/components/LabelCaptureScreen";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import {
  POLL_INTERVAL_MS,
  hasPendingWork,
  useIntervalPolling,
} from "@/state/polling";
import {
  useSession,
  toApiSession,
  type ApiSession,
  type Session,
} from "@/state/session";
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
/** Build a synthetic resolved food item from a saved food selection (FTY-053). */
function syntheticSavedFoodItem(
  savedFood: SavedFoodDTO,
  logEventId: string,
  userId: string,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `saved-${savedFood.id}`,
    user_id: userId,
    log_event_id: logEventId,
    name: savedFood.name,
    quantity_text: `${savedFood.serving_size} ${savedFood.serving_unit}`,
    unit: savedFood.serving_unit,
    amount: savedFood.serving_size,
    status: "resolved",
    grams: null,
    calories: savedFood.calories,
    protein_g: savedFood.protein_g,
    carbs_g: savedFood.carbs_g,
    fat_g: savedFood.fat_g,
    calories_estimated: savedFood.calories,
    protein_g_estimated: savedFood.protein_g,
    carbs_g_estimated: savedFood.carbs_g,
    fat_g_estimated: savedFood.fat_g,
    source: "saved_food",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

export function TodayScreen({
  session: sessionOverride,
  load = listTodayLogEventsApi,
  create = createLogEventApi,
  editItem = editDerivedItemApi,
  items: itemsOverride,
  useActive = useScreenActive,
  pollIntervalMs = POLL_INTERVAL_MS,
  searchSavedFoods = searchSavedFoodsApi,
  saveFood = saveFoodApi,
  uploadLabel = uploadLabelImageApi,
  labelTakePhoto,
  getDailySummary = getDailySummaryApi,
  onPressProfile,
}: {
  session?: Session;
  load?: typeof listTodayLogEventsApi;
  create?: typeof createLogEventApi;
  editItem?: typeof editDerivedItemApi;
  /**
   * Derived food/exercise items keyed by their `log_event_id`, rendered as
   * editable surfaces beneath each entry (FTY-050). The item list endpoint is a
   * later story, so this defaults to none today; edits reconcile the server's
   * returned item back into this map.
   */
  items?: Readonly<Record<string, readonly DerivedItem[]>>;
  useActive?: () => boolean;
  pollIntervalMs?: number;
  /** Injectable typeahead search for tests (FTY-053). */
  searchSavedFoods?: typeof searchSavedFoodsApi;
  /** Injectable save-food function for tests (FTY-053). */
  saveFood?: typeof saveFoodApi;
  /** Injectable label upload for tests (FTY-064). */
  uploadLabel?: typeof uploadLabelImageApi;
  /** Injectable photo capture for label-capture tests (FTY-064). */
  labelTakePhoto?: () => Promise<{ uri: string }>;
  /** Injectable daily summary fetch for tests (FTY-075). */
  getDailySummary?: typeof getDailySummaryApi;
  /** Called when the user presses the gear / profile icon in the header. */
  onPressProfile?: () => void;
} = {}) {
  const insets = useSafeAreaInsets();
  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

  const [events, setEvents] = useState<readonly LogEventDTO[]>([]);
  // Derived items keyed by event id. Seeded from the (injectable) prop; an edit
  // reconciles the server's returned item back into this map by its event id.
  const [itemsByEvent, setItemsByEvent] = useState<
    Readonly<Record<string, readonly DerivedItem[]>>
  >(itemsOverride ?? {});
  const [phase, setPhase] = useState<Phase>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [labelCaptureOpen, setLabelCaptureOpen] = useState(false);
  // Saved food selected from the typeahead bar (FTY-053). When set, pressing
  // "Add" creates the log event AND immediately adds a synthetic resolved item
  // with the saved food's nutrition, skipping the estimator wait.
  const [selectedSavedFood, setSelectedSavedFood] = useState<SavedFoodDTO | null>(null);
  // Daily summary: intake, macros, target, exercise burn (FTY-075).
  const [summary, setSummary] = useState<DailySummaryDTO | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
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

  // Load the daily summary (FTY-075): intake, macros, target, exercise burn.
  // Reuses the same session and polling mechanism as the timeline (FTY-032).
  useEffect(() => {
    if (!apiSession) {
      return;
    }
    let active = true;
    getDailySummary(apiSession).then(
      (loaded) => {
        if (!active) return;
        setSummary(loaded);
        setSummaryError(null);
      },
      () => {
        if (!active) return;
        setSummaryError(
          "We couldn't load your summary. Check your connection and try again.",
        );
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, getDailySummary, reloadKey]);

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
    // Capture and clear the selected saved food before the async path.
    const pendingSavedFood = selectedSavedFood;
    setSelectedSavedFood(null);

    // Show the new entry immediately as pending, then reconcile with the server.
    setEvents((prev) => sortByNewest([optimistic, ...prev]));

    // If a saved food was selected, add a synthetic resolved item immediately
    // with its stored nutrition — the estimator is bypassed for this item.
    if (pendingSavedFood) {
      const syntheticItem = syntheticSavedFoodItem(
        pendingSavedFood,
        id,
        apiSession.userId,
      );
      setItemsByEvent((prev) => ({ ...prev, [id]: [syntheticItem] }));
    }

    setText("");
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await create(apiSession, trimmed);
      setEvents((prev) =>
        sortByNewest(prev.map((event) => (event.id === id ? created : event))),
      );
      // Re-key the synthetic item from optimistic id to the real event id.
      if (pendingSavedFood) {
        setItemsByEvent((prev) => {
          const items = prev[id] ?? [];
          const updated = items.map((item) => ({
            ...item,
            log_event_id: created.id,
          }));
          const { [id]: _removed, ...rest } = prev;
          return { ...rest, [created.id]: updated };
        });
      }
    } catch (error) {
      // Roll back the optimistic entry and restore the input so nothing is lost.
      setEvents((prev) => prev.filter((event) => event.id !== id));
      if (pendingSavedFood) {
        setItemsByEvent((prev) => {
          const { [id]: _removed, ...rest } = prev;
          return rest;
        });
      }
      setText(trimmed);
      setSubmitError(messageFor(error, "save"));
    } finally {
      setSubmitting(false);
    }
  }, [text, apiSession, submitting, create, selectedSavedFood]);

  // Barcode scan entry point (FTY-063). Mirrors the text-composer submit flow:
  // dismiss the scanner, show the barcode as a pending optimistic entry, then
  // reconcile with the server. Rolls back cleanly on failure.
  const handleBarcodeScanned = useCallback(
    async (barcode: string) => {
      setScannerOpen(false);
      if (!apiSession || submitting) {
        return;
      }
      const id = `${OPTIMISTIC_ID_PREFIX}${tempId.current++}`;
      const optimistic = optimisticLogEvent({
        id,
        userId: apiSession.userId,
        rawText: barcode,
        createdAt: new Date().toISOString(),
      });
      setEvents((prev) => sortByNewest([optimistic, ...prev]));
      setSubmitting(true);
      setSubmitError(null);
      try {
        const created = await create(apiSession, barcode);
        setEvents((prev) =>
          sortByNewest(
            prev.map((event) => (event.id === id ? created : event)),
          ),
        );
      } catch (error) {
        setEvents((prev) => prev.filter((event) => event.id !== id));
        setSubmitError(messageFor(error, "save"));
      } finally {
        setSubmitting(false);
      }
    },
    [apiSession, submitting, create],
  );

  // Label capture upload (FTY-064). The backend created and extracted the event
  // in-request; add the returned event to the timeline directly and let FTY-032
  // polling reconcile any later status change.
  const handleLabelUploaded = useCallback((event: LogEventDTO) => {
    setLabelCaptureOpen(false);
    setEvents((prev) => sortByNewest([event, ...prev]));
  }, []);

  // One poll: refetch the day and reconcile into the timeline, preserving any
  // unacknowledged optimistic entry. Also refetch the daily summary so it
  // reflects any entries that have reached terminal status. Transient poll
  // failures are swallowed so a dropped request never replaces the visible
  // timeline with an error — the next tick retries, and the manual refresh
  // surfaces persistent failures.
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
    getDailySummary(apiSession).then(
      (loaded) => {
        setSummary(loaded);
        // Clear any stale error so a recovered poll drops the error banner —
        // DailySummary renders its error branch ahead of the summary, so without
        // this an initial-load failure would stick even once good data arrives.
        setSummaryError(null);
      },
      () => {
        // Keep the current summary and any existing error; retry next interval.
      },
    );
  }, [apiSession, load, getDailySummary]);

  // Reconcile a confirmed edit (the server's current item) back into the map,
  // replacing the prior item for its event by id so the timeline re-renders the
  // server values — including any servings-rescaled calories/macros.
  const handleItemChange = useCallback((updated: DerivedItem) => {
    setItemsByEvent((prev) => {
      const eventId = updated.log_event_id;
      const current = prev[eventId] ?? [];
      return {
        ...prev,
        [eventId]: current.map((item) =>
          item.id === updated.id ? updated : item,
        ),
      };
    });
  }, []);

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
    <>
      <Modal
        visible={scannerOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setScannerOpen(false)}
      >
        <BarcodeScannerScreen
          onBarcodeScanned={(barcode) => void handleBarcodeScanned(barcode)}
          onClose={() => setScannerOpen(false)}
        />
      </Modal>

      <Modal
        visible={labelCaptureOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setLabelCaptureOpen(false)}
      >
        {apiSession && (
          <LabelCaptureScreen
            session={apiSession}
            onUploaded={handleLabelUploaded}
            onClose={() => setLabelCaptureOpen(false)}
            upload={
              apiSession
                ? (imageUri, savePhoto) =>
                    uploadLabel(apiSession, imageUri, savePhoto)
                : undefined
            }
            takePhoto={labelTakePhoto}
          />
        )}
      </Modal>

      <ScrollView
        style={styles.screen}
        contentContainerStyle={[
          styles.content,
          // +96 (not +24) so the last entry clears the floating, absolutely-
          // positioned tab bar that now overlays the scroll content; mirrors
          // the placeholder tabs' insets.bottom + 80 reservation with extra
          // breathing room for a scrollable list.
          { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 96 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <Text style={styles.title} accessibilityRole="header">
            Today
          </Text>
          <View style={styles.headerActions}>
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
            {onPressProfile ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Open profile"
                accessibilityHint="Opens profile and settings"
                onPress={onPressProfile}
                style={styles.gearButton}
              >
                <Text style={styles.gearLabel}>⚙</Text>
              </Pressable>
            ) : null}
          </View>
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
          <View style={styles.composerActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Scan barcode"
              accessibilityHint="Opens the camera to scan a product barcode"
              accessibilityState={{ disabled: submitting }}
              disabled={submitting}
              onPress={() => setScannerOpen(true)}
              style={styles.scanButton}
            >
              <Text style={styles.scanButtonLabel}>⊡</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Capture label"
              accessibilityHint="Opens the camera to photograph a nutrition label"
              accessibilityState={{ disabled: submitting || !apiSession }}
              disabled={submitting || !apiSession}
              onPress={() => setLabelCaptureOpen(true)}
              style={styles.scanButton}
            >
              <Text style={styles.scanButtonLabel}>◉</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Add entry"
              accessibilityState={{ disabled: !canSubmit }}
              disabled={!canSubmit}
              onPress={() => void handleSubmit()}
              style={[styles.add, !canSubmit && styles.addDisabled]}
            >
              <Text style={styles.addLabel}>
                {submitting ? "Adding…" : "Add"}
              </Text>
            </Pressable>
          </View>
        </View>
        <TypeaheadSuggestionBar
          query={text}
          session={apiSession}
          onSelect={(food) => {
            setSelectedSavedFood(food);
            setText(food.name);
          }}
          search={searchSavedFoods}
        />
        {submitError ? (
          <Text style={styles.error} accessibilityRole="alert">
            {submitError}
          </Text>
        ) : null}

        <Timeline
          events={events}
          itemsByEvent={itemsByEvent}
          session={apiSession}
          editItem={editItem}
          onItemChange={handleItemChange}
          phase={phase}
          loadError={loadError}
          onRetry={() => void refresh()}
          saveFood={saveFood}
          summary={summary}
          summaryError={summaryError}
        />
      </ScrollView>
    </>
  );
}

function Timeline({
  events,
  itemsByEvent,
  session,
  editItem,
  onItemChange,
  phase,
  loadError,
  onRetry,
  saveFood,
  summary,
  summaryError,
}: {
  events: readonly LogEventDTO[];
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  session: ApiSession | null;
  editItem: typeof editDerivedItemApi;
  onItemChange: (item: DerivedItem) => void;
  phase: Phase;
  loadError: string | null;
  onRetry: () => void;
  saveFood: typeof saveFoodApi;
  summary?: DailySummaryDTO | null;
  summaryError?: string | null;
}) {
  if (events.length === 0) {
    if (phase === "loading") {
      return (
        <View style={styles.state}>
          <ActivityIndicator accessibilityLabel="Loading your day" />
        </View>
      );
    }
    // A day with nothing logged still has a summary: zeroed intake and the
    // calorie target. Render it (and any summary error) above the empty state so
    // the target is visible before the first entry — DailySummary returns null
    // when there is neither summary nor error, so this stays clean.
    return (
      <View>
        <DailySummary summary={summary} error={summaryError} />
        {phase === "error" ? (
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
        ) : (
          <View style={styles.state}>
            <Text style={styles.stateText}>
              Nothing logged yet. Add your first food or exercise above.
            </Text>
          </View>
        )}
      </View>
    );
  }

  return (
    <View>
      <DailySummary summary={summary} error={summaryError} />
      {phase === "error" && loadError ? (
        <Text style={styles.error} accessibilityRole="alert">
          {loadError}
        </Text>
      ) : null}
      <View style={styles.card}>
        {events.map((event) => (
          <EntryRow
            key={event.id}
            event={event}
            items={itemsByEvent[event.id]}
            session={session}
            editItem={editItem}
            onItemChange={onItemChange}
            saveFoodFn={saveFood}
          />
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
  headerActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  gearButton: {
    paddingVertical: 8,
    paddingHorizontal: 8,
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  gearLabel: {
    fontSize: 22,
    color: "#1C1C1E",
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
  composerActions: {
    flexDirection: "column",
    gap: 6,
    alignItems: "center",
  },
  scanButton: {
    width: 44,
    height: 44,
    borderRadius: 10,
    backgroundColor: "#E4E4EA",
    alignItems: "center",
    justifyContent: "center",
  },
  scanButtonLabel: {
    fontSize: 22,
    color: "#1C1C1E",
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
