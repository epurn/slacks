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
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
} from "@/api/corrections";
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
  confirmLabelProposal as confirmLabelProposalApi,
  getLabelProposal as getLabelProposalApi,
} from "@/api/labelProposal";
import {
  LogEventApiError,
  answerClarification as answerClarificationApi,
  createLogEvent as createLogEventApi,
  getLogEventClarification as getLogEventClarificationApi,
  listTodayLogEvents as listTodayLogEventsApi,
  listTodayLogEventEntries as listTodayLogEventEntriesApi,
  type LogEventDTO,
  type LogEventEntryDTO,
} from "@/api/logEvents";
import {
  saveFood as saveFoodApi,
  searchSavedFoods as searchSavedFoodsApi,
  type SavedFoodDTO,
} from "@/api/savedFoods";
import { AppIcon, ScreenHeader } from "@/components/ui";
import { BarcodeScannerScreen } from "@/components/BarcodeScannerScreen";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import {
  CorrectionSheet,
  type ClarificationData,
} from "@/components/CorrectionSheet";
import { DailySummary } from "@/components/DailySummary";
import { EntryRow } from "@/components/EntryRow";
import { ItemTimelineRow } from "@/components/ItemTimelineRow";
import { LabelCaptureScreen } from "@/components/LabelCaptureScreen";
import { ConfirmParsedValuesSheet } from "@/components/ConfirmParsedValuesSheet";
import { MacroTier } from "@/components/MacroTier";
import { OfflineEntryRow } from "@/components/OfflineEntryRow";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import {
  generateIdempotencyKey,
  type OutboxStore,
  type OutboxSyncState,
} from "@/state/outbox";
import { fileOutboxStore } from "@/state/outboxStore";
import {
  POLL_INTERVAL_MS,
  hasPendingWork,
  useIntervalPolling,
} from "@/state/polling";
import {
  useSession,
  toApiSession,
  type Session,
} from "@/state/session";
import {
  OPTIMISTIC_ID_PREFIX,
  clusterByTime,
  formatWallClockTime,
  optimisticLogEvent,
  reconcileEvents,
  sortByNewest,
  statusPresentation,
} from "@/state/today";
import { useScreenActive } from "@/state/useScreenActive";
import { useSubmitLog, type SubmitLogBridge } from "@/state/useSubmitLog";
import { useTheme, spacing, typeScale, radius, reducedMotionDuration } from "@/theme";
import { entryResolvedHaptic } from "@/theme/haptics";

/** Maximum raw-text length, mirrored from the FTY-030 contract. */
const MAX_RAW_TEXT_LENGTH = 2000;

type Phase = "loading" | "ready" | "error";

function itemTimelineRowTestID(eventId: string): string {
  return `item-timeline-row-${eventId}`;
}

function itemTimelineExtraRowTestID(eventId: string, itemId: string): string {
  return `item-timeline-row-${eventId}-${itemId}`;
}

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
/**
 * Id prefix for the synthetic saved-food row built locally on a saved-food add
 * (FTY-053). It marks a client-built resolved row so the items-forward timeline
 * can tell a true optimistic/saved-food row from a server-fed by-date item —
 * server ids are UUIDs and never carry this prefix.
 */
const SAVED_FOOD_ITEM_ID_PREFIX = "saved-";

/**
 * Whether an item is a locally-built synthetic saved-food row (FTY-053) rather
 * than a server-fed derived item (FTY-198). Used to gate the items-forward
 * fallback to true optimistic/saved-food rows so a server row can only surface
 * through the completed branch — the pending→completed transition that resolves
 * the skeleton in place (FTY-180) and arms the entry-resolve beat (FTY-181),
 * never a mid-poll swap keyed by item id.
 */
function isSyntheticSavedFoodItem(item: DerivedItem): boolean {
  return item.id.startsWith(SAVED_FOOD_ITEM_ID_PREFIX);
}

/** Build a synthetic resolved food item from a saved food selection (FTY-053). */
function syntheticSavedFoodItem(
  savedFood: SavedFoodDTO,
  logEventId: string,
  userId: string,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `${SAVED_FOOD_ITEM_ID_PREFIX}${savedFood.id}`,
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
    source: null,
    is_edited: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

/**
 * Build the placeholder item the clarify-mode sheet opens against for a
 * `needs_clarification` event (FTY-149). A needs-clarification event has no
 * resolved derived item — the parse stopped for a missing detail — so the sheet
 * (which is item-addressed) is fed a minimal, uncounted stand-in: the typed
 * phrase as the name, no nutrition. Clarify-mode only reads `name`/`id`; it never
 * shows or commits these null values, so the item is never counted and the
 * detail is never auto-filled.
 */
function clarificationPlaceholderItem(
  event: LogEventDTO,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `clarify-${event.id}`,
    user_id: event.user_id,
    log_event_id: event.id,
    name: event.raw_text,
    quantity_text: event.raw_text,
    unit: null,
    amount: null,
    status: "unresolved",
    grams: null,
    calories: null,
    protein_g: null,
    carbs_g: null,
    fat_g: null,
    calories_estimated: null,
    protein_g_estimated: null,
    carbs_g_estimated: null,
    fat_g_estimated: null,
    source: null,
    is_edited: false,
    created_at: event.created_at,
    updated_at: event.updated_at,
  };
}

/**
 * Drop an optimistic event and its synthetic saved-food item from Today's state
 * by optimistic id — shared by the server-error rollback and the unreachable
 * discard paths the submit machine drives through the bridge.
 */
function removeOptimisticEvent(
  setEvents: React.Dispatch<React.SetStateAction<readonly LogEventDTO[]>>,
  setItemsByEvent: React.Dispatch<
    React.SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >,
  optimisticId: string,
): void {
  setEvents((prev) => prev.filter((event) => event.id !== optimisticId));
  setItemsByEvent((prev) => {
    if (!(optimisticId in prev)) return prev;
    const { [optimisticId]: _removed, ...rest } = prev;
    return rest;
  });
}

function hasOwn(object: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

/**
 * Fold the item-forward feed into the items map. Derived items replace prior
 * rows; completed empty entries are recorded as a settled-empty `[]` without
 * wiping existing items.
 */
function mergeServerItems(
  prev: Readonly<Record<string, readonly DerivedItem[]>>,
  entries: readonly LogEventEntryDTO[],
): Readonly<Record<string, readonly DerivedItem[]>> {
  let next: Record<string, readonly DerivedItem[]> | null = null;
  for (const entry of entries) {
    if (entry.items.length > 0) {
      next ??= { ...prev };
      next[entry.event.id] = entry.items;
    } else if (
      entry.event.status === "completed" &&
      !hasOwn(prev, entry.event.id)
    ) {
      next ??= { ...prev };
      next[entry.event.id] = [];
    }
  }
  return next ?? prev;
}

export function TodayScreen({
  session: sessionOverride,
  load = listTodayLogEventsApi,
  loadEntries = listTodayLogEventEntriesApi,
  create = createLogEventApi,
  getClarification = getLogEventClarificationApi,
  answerClarification = answerClarificationApi,
  editItem = editDerivedItemApi,
  items: itemsOverride,
  useActive = useScreenActive,
  pollIntervalMs = POLL_INTERVAL_MS,
  searchSavedFoods = searchSavedFoodsApi,
  saveFood = saveFoodApi,
  listSourceCandidates = listSourceCandidatesApi,
  reResolveItem = reResolveItemApi,
  uploadLabel = uploadLabelImageApi,
  labelTakePhoto,
  getLabelProposal = getLabelProposalApi,
  confirmLabelProposal = confirmLabelProposalApi,
  getDailySummary = getDailySummaryApi,
  outboxStore = fileOutboxStore,
  retryIntervalMs,
  generateKey = generateIdempotencyKey,
  now = () => new Date().toISOString(),
  onPressProfile,
}: {
  session?: Session;
  load?: typeof listTodayLogEventsApi;
  /**
   * Item-forward day feed (FTY-198): each event with its derived value rows. Read
   * alongside `load` (which carries event envelopes only) so a completed entry's
   * resolved value rows populate `itemsByEvent` from real server data — the data
   * path a pending row's skeleton resolves into in place (FTY-180) and the
   * entry-resolve beat's (FTY-181) real data path. Injectable for tests.
   */
  loadEntries?: typeof listTodayLogEventEntriesApi;
  create?: typeof createLogEventApi;
  /** Injectable clarification-question read for the clarify sheet (FTY-153). */
  getClarification?: typeof getLogEventClarificationApi;
  /** Injectable clarification answer round-trip for the clarify sheet (FTY-170/175). */
  answerClarification?: typeof answerClarificationApi;
  editItem?: typeof editDerivedItemApi;
  /**
   * Derived food/exercise items keyed by their `log_event_id`, rendered as
   * editable surfaces beneath each entry (FTY-050). Seeds the map; the item-
   * forward by-date feed (`loadEntries`, FTY-198) folds real server items in as
   * events reach `completed`, and edits reconcile the server's returned item back
   * into this map.
   */
  items?: Readonly<Record<string, readonly DerivedItem[]>>;
  useActive?: () => boolean;
  pollIntervalMs?: number;
  /** Injectable typeahead search for tests (FTY-053). */
  searchSavedFoods?: typeof searchSavedFoodsApi;
  /** Injectable save-food function for tests (FTY-053). */
  saveFood?: typeof saveFoodApi;
  /** Injectable change-match candidate list for the correction sheet (FTY-093). */
  listSourceCandidates?: typeof listSourceCandidatesApi;
  /** Injectable re-resolve for the correction sheet's change-match lever (FTY-093). */
  reResolveItem?: typeof reResolveItemApi;
  /** Injectable label upload for tests (FTY-064). */
  uploadLabel?: typeof uploadLabelImageApi;
  /** Injectable photo capture for label-capture tests (FTY-064). */
  labelTakePhoto?: () => Promise<{ uri: string }>;
  /** Injectable proposed-values read for the confirm sheet (FTY-196/197). */
  getLabelProposal?: typeof getLabelProposalApi;
  /** Injectable confirm action for the confirm sheet (FTY-196/197). */
  confirmLabelProposal?: typeof confirmLabelProposalApi;
  /** Injectable daily summary fetch for tests (FTY-075). */
  getDailySummary?: typeof getDailySummaryApi;
  /** Durable offline-outbox storage (FTY-104, harvested onto Today in FTY-147). */
  outboxStore?: OutboxStore;
  /** Reconnect-retry cadence for the outbox drain — injectable for tests. */
  retryIntervalMs?: number;
  /** Idempotency-key generator — injectable for deterministic tests. */
  generateKey?: () => string;
  /** Capture-timestamp source — injectable for deterministic tests. */
  now?: () => string;
  /** Called when the user presses the gear / profile icon in the header. */
  onPressProfile?: () => void;
} = {}) {
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
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
  const [scannerOpen, setScannerOpen] = useState(false);
  const [labelCaptureOpen, setLabelCaptureOpen] = useState(false);
  // The uncounted label parse awaiting confirm/adjust (FTY-196/197). Set after a
  // legible label upload; the confirm sheet renders it and commits it — until
  // then it never counts. `null` when there is no proposal to confirm.
  const [labelProposal, setLabelProposal] = useState<DerivedFoodItemDTO | null>(
    null,
  );
  const [labelProposalVisible, setLabelProposalVisible] = useState(false);
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
  // Composer input handle so "Edit as text" (FTY-176) can focus it after
  // prefilling the failed entry's wording — the keyboard rises in place.
  const inputRef = useRef<TextInput>(null);
  // The single mounted correction/detail sheet (FTY-100, wired here in FTY-148).
  // `target` holds the tapped item + its log phrase; `visible` drives the slide
  // animation. We keep `target` set across a close so the sheet can animate out
  // without the item vanishing mid-transition; a new tap replaces it in place.
  const [sheetTarget, setSheetTarget] = useState<{
    item: DerivedItem;
    logPhrase: string;
    /** True when the sheet opens in clarify-mode for a needs_clarification event. */
    needsClarification?: boolean;
    /** The needs_clarification event id being resolved (clarify-mode only). */
    eventId?: string;
    /**
     * The clarification question's stable id — the key the answer round-trip
     * (FTY-170) references. `null` until the clarification read resolves; an
     * answer can only be submitted once it is known.
     */
    questionId?: string | null;
    /**
     * Fatty's question + options for clarify-mode (FTY-153/170). Seeded with a
     * `null` question (the generic-prompt + free-text fallback) and filled in
     * place — question text + quick-pick chips — once the clarification read
     * resolves. Calm, no layout jump.
     */
    clarificationData?: ClarificationData;
  } | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);
  // Failed events the user has retried / handed to the composer this session
  // (FTY-176). This is render state only: a
  // retried failed row is superseded in place by the fresh attempt (or by the
  // composer resubmission), so it is filtered from the timeline even though the
  // server still lists the original as `failed`. A create-call error un-hides
  // the original so the failed row stays actionable — never a dead end.
  const [supersededFailedIds, setSupersededFailedIds] = useState<
    ReadonlySet<string>
  >(() => new Set());

  // Beat 1 — entry resolve. Detect pending→`completed` (counted) transitions so a
  // resolve fires the soft-tap haptic once per resolved event and eases the
  // resolved value's row in. `seenCompleted` is `null` until the first events load
  // seeds it, so an already-completed entry present on initial load never beats on
  // mount. The detection runs in render (the "adjust state on prop change" pattern
  // used elsewhere in this file), and a `resolveBeatCount` — advanced by the number
  // of freshly-resolved events each reconciliation — hands the actual haptics to an
  // effect (a side effect must not run during render). The effect fires the delta
  // since it last ran, so a poll batch where several entries complete at once beats
  // once per event, not one tap total (FTY-181 review).
  const [seenCompleted, setSeenCompleted] = useState<ReadonlySet<string> | null>(
    null,
  );
  const [resolveAnimIds, setResolveAnimIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [resolveBeatCount, setResolveBeatCount] = useState(0);
  const firedResolveBeats = useRef(0);

  // The submit machine reads the latest selected saved food at submit time, and
  // each in-flight submit stashes its saved food by optimistic id so the right
  // one is re-keyed on success / restored on a server-error rollback. The ref is
  // synced in an effect (never during render) per the project's ref convention.
  const selectedSavedFoodRef = useRef<SavedFoodDTO | null>(null);
  useEffect(() => {
    selectedSavedFoodRef.current = selectedSavedFood;
  });
  const pendingSavedFoodById = useRef(new Map<string, SavedFoodDTO | null>());

  // Today's optimistic-timeline operations, handed to the shared submit machine
  // (FTY-147). The machine owns create/optimistic/offline/rollback; the
  // saved-food synthetic item (FTY-053) stays here, behind these callbacks.
  const submitBridge = useMemo<SubmitLogBridge>(
    () => ({
      insertOptimistic(optimistic) {
        setEvents((prev) => sortByNewest([optimistic, ...prev]));
        const savedFood = selectedSavedFoodRef.current;
        pendingSavedFoodById.current.set(optimistic.id, savedFood);
        // A selected saved food carries resolved nutrition immediately — add a
        // synthetic resolved item so the estimator is bypassed for this entry.
        if (savedFood && apiSession) {
          const syntheticItem = syntheticSavedFoodItem(
            savedFood,
            optimistic.id,
            apiSession.userId,
          );
          setItemsByEvent((prev) => ({ ...prev, [optimistic.id]: [syntheticItem] }));
        }
        setSelectedSavedFood(null);
      },
      reconcileOptimistic(optimisticId, server) {
        setEvents((prev) =>
          sortByNewest(
            prev.map((event) => (event.id === optimisticId ? server : event)),
          ),
        );
        setItemsByEvent((prev) => {
          const items = prev[optimisticId];
          if (!items) return prev;
          const updated = items.map((item) => ({
            ...item,
            log_event_id: server.id,
          }));
          const { [optimisticId]: _removed, ...rest } = prev;
          return { ...rest, [server.id]: updated };
        });
        pendingSavedFoodById.current.delete(optimisticId);
      },
      rollbackOptimistic(optimisticId) {
        removeOptimisticEvent(setEvents, setItemsByEvent, optimisticId);
        // Restore the saved-food association so retry is one tap (server error).
        const savedFood = pendingSavedFoodById.current.get(optimisticId) ?? null;
        pendingSavedFoodById.current.delete(optimisticId);
        if (savedFood) setSelectedSavedFood(savedFood);
      },
      discardOptimistic(optimisticId) {
        // Unreachable: the capture is kept as an offline row, not restored to the
        // composer — so the saved-food association is dropped, not restored.
        removeOptimisticEvent(setEvents, setItemsByEvent, optimisticId);
        pendingSavedFoodById.current.delete(optimisticId);
      },
      acceptDrained(_idempotencyKey, event) {
        // A drained offline capture folds into the normal flow: insert the real
        // server event (deduped by id) and let polling reconcile it to terminal.
        setEvents((prev) =>
          sortByNewest([event, ...prev.filter((e) => e.id !== event.id)]),
        );
      },
    }),
    [apiSession],
  );

  const {
    text,
    setText,
    submitting,
    setSubmitting,
    submitError,
    setSubmitError,
    handleSubmit,
    reachability,
    offlineEntries,
    queuedCount,
  } = useSubmitLog({
    session: apiSession,
    bridge: submitBridge,
    create,
    outboxStore,
    retryIntervalMs,
    generateKey,
    now,
  });

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

  // Load the item-forward day feed (FTY-198) beside the event list so completed
  // entries can render value rows from real server data (FTY-180/181). A read
  // failure is swallowed; the next poll retries without replacing the timeline.
  useEffect(() => {
    if (!apiSession) {
      return;
    }
    let active = true;
    loadEntries(apiSession).then(
      (entries) => {
        if (!active) return;
        setItemsByEvent((prev) => mergeServerItems(prev, entries));
      },
      () => {
        // Keep whatever items are already shown; the next poll retries.
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, loadEntries, reloadKey]);

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

  // Beat 1 detection (render phase). Compute the set of completed event ids and,
  // once seeded, diff it against the last-seen set: any newly-completed id is a
  // pending→resolved transition. Detection only starts once the first load has
  // landed (`phase === "ready"`); the seed then captures the initially-loaded
  // completed entries, so an entry already completed on load is never treated as a
  // fresh resolve — no beat on mount.
  const completedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const event of events) {
      if (event.status === "completed") ids.add(event.id);
    }
    return ids;
  }, [events]);
  if (phase === "ready") {
    if (seenCompleted === null) {
      setSeenCompleted(completedIds);
    } else {
      const fresh: string[] = [];
      for (const id of completedIds) {
        if (!seenCompleted.has(id)) fresh.push(id);
      }
      if (fresh.length > 0) {
        setSeenCompleted(completedIds);
        setResolveAnimIds((prev) => {
          const next = new Set(prev);
          for (const id of fresh) next.add(id);
          return next;
        });
        setResolveBeatCount((n) => n + fresh.length);
      }
    }
  }

  // Fire one entry-resolve haptic per newly-resolved event.
  useEffect(() => {
    const unfired = resolveBeatCount - firedResolveBeats.current;
    if (unfired <= 0) return;
    firedResolveBeats.current = resolveBeatCount;
    for (let i = 0; i < unfired; i++) entryResolvedHaptic();
  }, [resolveBeatCount]);

  useEffect(() => {
    if (resolveAnimIds.size === 0) return;
    const timeout = setTimeout(() => {
      setResolveAnimIds((prev) => {
        let next: Set<string> | null = null;
        for (const id of prev) {
          if (hasOwn(itemsByEvent, id)) {
            next ??= new Set(prev);
            next.delete(id);
          }
        }
        return next ?? prev;
      });
    }, reducedMotionDuration);
    return () => clearTimeout(timeout);
  }, [itemsByEvent, resolveAnimIds]);

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
    [apiSession, submitting, create, setSubmitting, setSubmitError],
  );

  // Label capture upload (FTY-064 + FTY-196/197). The backend created and
  // extracted the event in-request; add the returned event to the timeline, then
  // read its label proposal (FTY-196). A legible parse lands as an **uncounted
  // proposal** — never silently counted — so instead of dropping to Today we
  // present the confirm-parsed-values sheet (FTY-197) for the user to confirm or
  // adjust before it counts. The proposed item is stashed into the timeline so
  // the entry is honestly surfaced as "not yet counted" if the user dismisses.
  //
  // An unreadable / not-a-label result has no proposal (`null`): the existing
  // retake-or-type handling is unchanged — the event stays in the timeline in its
  // post-extraction status (needs_clarification / failed) with no confirm sheet.
  const handleLabelUploaded = useCallback(
    (event: LogEventDTO) => {
      setLabelCaptureOpen(false);
      setEvents((prev) => sortByNewest([event, ...prev]));
      if (!apiSession) return;
      getLabelProposal(apiSession, event.id).then(
        (proposal) => {
          if (!proposal) return; // unreadable / not-a-label — path unchanged
          setItemsByEvent((prev) => ({
            ...prev,
            [event.id]: [proposal],
          }));
          setLabelProposal(proposal);
          setLabelProposalVisible(true);
        },
        () => {
          // Reading the proposal failed transiently; leave the event in the
          // timeline. The user can reopen capture rather than being dead-ended.
        },
      );
    },
    [apiSession, getLabelProposal],
  );

  // Confirm the label proposal (FTY-196/197). The committed item is `resolved`
  // and now counts: swap it into the timeline in place of the proposed item and
  // refetch the daily summary so Today's totals update — the immediate, in-place
  // acknowledgement, no jarring navigation ("Acknowledge every action" / "Calm by
  // default").
  const handleProposalConfirmed = useCallback(
    (committed: DerivedFoodItemDTO) => {
      setLabelProposalVisible(false);
      setLabelProposal(null);
      setItemsByEvent((prev) => ({
        ...prev,
        [committed.log_event_id]: [committed],
      }));
      if (!apiSession) return;
      getDailySummary(apiSession).then(
        (loaded) => {
          setSummary(loaded);
          setSummaryError(null);
        },
        () => {
          // Keep the current summary; the poll loop reconciles totals shortly.
        },
      );
    },
    [apiSession, getDailySummary],
  );

  // Dismiss the confirm sheet without confirming: the proposal stays an uncounted
  // proposal (no confirm call fired). It remains in the timeline as a "not yet
  // counted" row the user can reopen — never silently counted, never a dead end.
  const handleProposalDismissed = useCallback(() => {
    setLabelProposalVisible(false);
  }, []);

  // Reopen the confirm sheet for an already-read proposal the user tapped in the
  // timeline (they dismissed it earlier). No refetch — the stashed item is the
  // proposal to confirm.
  const handleReopenProposal = useCallback((item: DerivedFoodItemDTO) => {
    setLabelProposal(item);
    setLabelProposalVisible(true);
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
    // Refresh the item-forward feed too, so an entry that reached `completed`
    // this tick shows its resolved value rows, the skeleton resolves in place,
    // and the entry-resolve beat can fire on the transition (FTY-180/181/198).
    loadEntries(apiSession).then(
      (entries) => {
        setItemsByEvent((prev) => mergeServerItems(prev, entries));
      },
      () => {
        // Keep the current items; retry on the next interval.
      },
    );
    getDailySummary(apiSession).then(
      (loaded) => {
        setSummary(loaded);
        // Clear any stale error so a recovered poll drops the inline summary
        // error once good data arrives.
        setSummaryError(null);
      },
      () => {
        // Keep the current summary and any existing error; retry next interval.
      },
    );
  }, [apiSession, load, loadEntries, getDailySummary]);

  // Open the correction/detail sheet for a tapped timeline item (FTY-148). The
  // sheet stays put — the timeline does not navigate away — honouring "calm by
  // default": a correction happens in a slide-up sheet, not a screen push.
  const openItemSheet = useCallback((item: DerivedItem, logPhrase: string) => {
    setSheetTarget({ item, logPhrase });
    setSheetVisible(true);
  }, []);
  const closeItemSheet = useCallback(() => setSheetVisible(false), []);

  // Open the correction sheet in clarify-mode for a needs_clarification entry
  // (FTY-149/153). Reuses the single mounted sheet via a minimal placeholder item;
  // clarify-mode shows Fatty's question (when known) + quick-pick chips + the
  // free-text fallback, and never auto-fills the missing detail.
  //
  // The sheet opens immediately at a usable height with the generic prompt, then
  // fetches FTY-152's clarification read and fills Fatty's real question in place
  // when it resolves (calm, no layout jump). A loading/empty/error read leaves the
  // generic prompt + free-text path intact — the user is never blocked.
  const openClarifySheet = useCallback(
    (event: LogEventDTO) => {
      setSheetTarget({
        item: clarificationPlaceholderItem(event),
        logPhrase: event.raw_text,
        needsClarification: true,
        eventId: event.id,
        questionId: null,
        clarificationData: { question: null, options: [] },
      });
      setSheetVisible(true);
      if (!apiSession) return;
      getClarification(apiSession, event.id).then(
        (result) => {
          const first = result.questions[0];
          if (!first) return;
          // Only fill if the sheet still targets this event (the user may have
          // tapped a different entry while the read was in flight). Fill Fatty's
          // real question + its candidate quick-pick chips in place — calm, no
          // layout jump — and stash the question id the answer round-trip needs.
          setSheetTarget((prev) =>
            prev && prev.eventId === event.id
              ? {
                  ...prev,
                  questionId: first.id,
                  clarificationData: {
                    question: first.text,
                    options: first.options,
                  },
                }
              : prev,
          );
        },
        () => {
          // Keep the generic prompt + free-text fallback; never block the user.
        },
      );
    },
    [apiSession, getClarification],
  );

  // Resolve a needs_clarification entry from the user's answer (FTY-170/175).
  // The answer — a tapped chip or free text — travels the first-class answer
  // round-trip: it is applied as a structured detail to the *same* event, which
  // the backend re-estimates in place. This replaces the retired create-path
  // re-submission (FTY-149) that mutated the raw phrase and spawned a duplicate
  // (audit A3/A5). The response is the same event now `processing`, so we swap it
  // in place: the row drops its needs-a-detail treatment immediately, polling
  // drives it to `completed`, and the daily summary then counts it — calm, no
  // navigation, no second row, never auto-filled.
  const handleClarificationResolved = useCallback(
    async (eventId: string, questionId: string | null, answer: string) => {
      closeItemSheet();
      if (!apiSession) return;
      const trimmed = answer.trim();
      if (!trimmed) return;
      try {
        // The sheet's opening read may still be in flight (or have failed) when
        // the user submits the free-text fallback, so the loading/error states
        // stay genuinely non-blocking: re-read the question id at submit time
        // and answer against it — the answer is never silently dropped.
        let resolvedQuestionId = questionId;
        if (!resolvedQuestionId) {
          const clarification = await getClarification(apiSession, eventId);
          resolvedQuestionId = clarification.questions[0]?.id ?? null;
        }
        if (!resolvedQuestionId) {
          // The event has no persisted question to answer against (empty
          // payload). Surface honestly rather than dead-ending; the row stays
          // as needs-a-detail and remains tappable.
          setSubmitError(
            "We couldn't load the question. Reopen the entry and try again.",
          );
          return;
        }
        const updated = await answerClarification(
          apiSession,
          eventId,
          resolvedQuestionId,
          trimmed,
        );
        // Same event, updated in place (needs_clarification → processing). No
        // optimistic second event: the resolve mutates the one entry server-side.
        setEvents((prev) =>
          sortByNewest(prev.map((e) => (e.id === eventId ? updated : e))),
        );
      } catch (error) {
        setSubmitError(messageFor(error, "save"));
      }
    },
    [
      apiSession,
      answerClarification,
      getClarification,
      closeItemSheet,
      setSubmitError,
    ],
  );

  // Retry a failed parse as a fresh attempt (FTY-176). There is no server-side
  // resubmit endpoint (a non-goal), so this reuses the existing create path: the
  // same `raw_text` is re-submitted with a NEW idempotency key, so it is a
  // genuine new attempt — not a dedup replay of the failed one. It reuses the
  // composer's optimistic-insert + poll-to-terminal pattern: the failed row is
  // superseded in place by the new pending attempt (no stale duplicate), and a
  // create-call error un-hides the original so it stays actionable — never a
  // dead end, never a fabricated number.
  const handleRetryFailed = useCallback(
    async (failedEvent: LogEventDTO) => {
      if (!apiSession) return;
      const rawText = failedEvent.raw_text;
      setSupersededFailedIds((prev) => new Set(prev).add(failedEvent.id));
      const id = `${OPTIMISTIC_ID_PREFIX}${tempId.current++}`;
      const optimistic = optimisticLogEvent({
        id,
        userId: apiSession.userId,
        rawText,
        createdAt: new Date().toISOString(),
      });
      setEvents((prev) => sortByNewest([optimistic, ...prev]));
      try {
        const created = await create(apiSession, rawText, generateKey());
        setEvents((prev) =>
          sortByNewest(prev.map((e) => (e.id === id ? created : e))),
        );
      } catch (error) {
        setEvents((prev) => prev.filter((e) => e.id !== id));
        // Un-hide the original failed row so a retry that couldn't even reach a
        // fresh attempt leaves the user a reachable path (no silent dead end).
        setSupersededFailedIds((prev) => {
          const next = new Set(prev);
          next.delete(failedEvent.id);
          return next;
        });
        setSubmitError(messageFor(error, "save"));
      }
    },
    [apiSession, create, generateKey, setSubmitError],
  );

  // Edit a failed parse as text (FTY-176). Prefill the composer with the failed
  // entry's `raw_text` so the user can fix the wording, then resubmit through the
  // same create path (the composer's submit machine mints a fresh idempotency
  // key). The failed row is superseded in place — no stale duplicate — and the
  // text is safe in the composer; a resubmission is a genuine new attempt.
  const handleEditFailedAsText = useCallback(
    (failedEvent: LogEventDTO) => {
      setText(failedEvent.raw_text);
      setSupersededFailedIds((prev) => new Set(prev).add(failedEvent.id));
      inputRef.current?.focus();
    },
    [setText],
  );

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

  const hasFreshResolveAwaitingItems = useMemo(() => {
    for (const id of resolveAnimIds) {
      if (!hasOwn(itemsByEvent, id)) return true;
    }
    return false;
  }, [itemsByEvent, resolveAnimIds]);

  // Poll while an event is in flight, or while a fresh completion is still
  // waiting for the item-forward feed to settle. That keeps the skeleton on the
  // same row if `/log-events/by-date` lags the event list.
  const isActive = useActive();
  const shouldPoll =
    phase === "ready" &&
    isActive &&
    !submitting &&
    (hasPendingWork(events) || hasFreshResolveAwaitingItems);
  useIntervalPolling(shouldPoll, pollIntervalMs, pollOnce);

  // Offline-queued captures (FTY-104, harvested onto Today in FTY-147). Each
  // renders as a dedicated, uncounted OfflineEntryRow in the timeline — never an
  // offline branch inside EntryRow (which carries FTY-148/149 behaviour). They
  // are kept out of `events` so the poll reconciler only ever sees server rows.
  const offlineStateById = useMemo(() => {
    const byId = new Map<string, OutboxSyncState>();
    for (const entry of offlineEntries) {
      if (entry.syncState !== "accepted") {
        byId.set(entry.idempotencyKey, entry.syncState);
      }
    }
    return byId;
  }, [offlineEntries]);

  // A synthetic pending event per offline capture, merged into the render list
  // (not `events`) so the timeline clusters them newest-first alongside server
  // rows; ClusterView renders them through OfflineEntryRow by their id.
  const displayEvents = useMemo(() => {
    // Drop entries the user has retried / handed to the composer (failed,
    // FTY-176) this session — they are superseded in place by the fresh attempt,
    // even after a poll re-fetches the original server row in its pre-retry
    // status. Answered needs_clarification entries need no such filter: the
    // FTY-170 resolve transitions the same event in place (→ processing), so the
    // real server row already drops its needs-a-detail treatment (FTY-175).
    const visible =
      supersededFailedIds.size === 0
        ? events
        : events.filter((event) => !supersededFailedIds.has(event.id));
    if (offlineEntries.length === 0) return visible;
    const offlineEvents = offlineEntries
      .filter((entry) => entry.syncState !== "accepted")
      .map((entry) =>
        optimisticLogEvent({
          id: entry.idempotencyKey,
          userId: entry.userId,
          rawText: entry.rawText,
          createdAt: entry.capturedAt,
        }),
      );
    return sortByNewest([...visible, ...offlineEvents]);
  }, [events, offlineEntries, supersededFailedIds]);

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
        testID="today-screen"
        style={[styles.screen, { backgroundColor: colors.surface }]}
        contentContainerStyle={[
          styles.content,
          // +96 (not +24) so the last entry clears the floating, absolutely-
          // positioned tab bar that now overlays the scroll content; mirrors
          // the placeholder tabs' insets.bottom + 80 reservation with extra
          // breathing room for a scrollable list.
          { paddingBottom: insets.bottom + 96 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <ScreenHeader
          title="Today"
          actions={
            <>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Refresh"
                accessibilityState={{ disabled: phase === "loading" }}
                disabled={phase === "loading"}
                onPress={() => void refresh()}
                style={styles.headerAction}
              >
                <AppIcon name="arrow.clockwise" size={20} color={colors.accent} />
              </Pressable>
              {onPressProfile ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Open profile"
                  accessibilityHint="Opens profile and settings"
                  onPress={onPressProfile}
                  style={styles.headerAction}
                >
                  <AppIcon name="gear" size={22} color={colors.text} />
                </Pressable>
              ) : null}
            </>
          }
        />

        {/* Calm connection banner between header and composer; self-hides when
            online and caught up (FTY-104, harvested onto Today in FTY-147). */}
        <ConnectionBanner state={reachability} queuedCount={queuedCount} />

        {/* Hero first, composer directly beneath it (FTY-178 Q-A1 default);
            the macro tier renders below the composer — reworking it is FTY-179. */}
        <DailySummary summary={summary} error={summaryError} onRetry={refresh} showMacros={false} />

        <View style={styles.composer}>
          <TextInput
            ref={inputRef}
            accessibilityLabel="Log food or exercise"
            placeholder="Add food or exercise…"
            placeholderTextColor={colors.textMuted}
            value={text}
            onChangeText={setText}
            multiline
            maxLength={MAX_RAW_TEXT_LENGTH}
            editable={!submitting}
            style={[styles.input, { backgroundColor: colors.surfaceRaised, color: colors.text }]}
          />
          <View style={styles.composerActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Scan barcode"
              accessibilityHint="Opens the camera to scan a product barcode"
              accessibilityState={{ disabled: submitting }}
              disabled={submitting}
              onPress={() => setScannerOpen(true)}
              style={[styles.scanButton, { backgroundColor: colors.controlBackground }]}
            >
              <AppIcon
                name="barcode.viewfinder"
                size={20}
                color={colors.text}
              />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Capture label"
              accessibilityHint="Opens the camera to photograph a nutrition label"
              accessibilityState={{ disabled: submitting || !apiSession }}
              disabled={submitting || !apiSession}
              onPress={() => setLabelCaptureOpen(true)}
              style={[styles.scanButton, { backgroundColor: colors.controlBackground }]}
            >
              <AppIcon
                name="camera.fill"
                size={20}
                color={colors.text}
              />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Add entry"
              accessibilityState={{ disabled: !canSubmit }}
              disabled={!canSubmit}
              onPress={() => void handleSubmit()}
              style={[
                styles.add,
                { backgroundColor: canSubmit ? colors.accent : colors.controlBackground },
              ]}
            >
              <Text style={[styles.addLabel, { color: canSubmit ? colors.accentForeground : colors.textMuted }]}>
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
          <Text style={[styles.error, { color: colors.coral }]} accessibilityRole="alert">
            {submitError}
          </Text>
        ) : null}

        {/* Macro tier in its pre-FTY-178 spot beneath the composer; the hero
            above owns the loading/unavailable shells. */}
        {summary ? (
          <MacroTier
            protein_g={summary.intake.protein_g}
            carbs_g={summary.intake.carbs_g}
            fat_g={summary.intake.fat_g}
            target={summary.target}
            active_calories={summary.exercise.active_calories}
          />
        ) : null}

        <Timeline
          events={displayEvents}
          itemsByEvent={itemsByEvent}
          offlineStateById={offlineStateById}
          resolveAnimIds={resolveAnimIds}
          onOpenItem={openItemSheet}
          onOpenProposal={handleReopenProposal}
          onOpenClarify={openClarifySheet}
          onRetryFailed={(event) => void handleRetryFailed(event)}
          onEditFailedAsText={handleEditFailedAsText}
          phase={phase}
          loadError={loadError}
          onRetry={() => void refresh()}
        />
      </ScrollView>

      {/* The single correction/detail sheet, reused for every tapped item. The
          clarify and normal forms are split so the discriminated prop contract
          (clarificationData required when needsClarification) holds at the call
          site, not just in a comment. */}
      {apiSession && sheetTarget ? (
        sheetTarget.needsClarification && sheetTarget.eventId ? (
          <CorrectionSheet
            item={sheetTarget.item}
            logPhrase={sheetTarget.logPhrase}
            visible={sheetVisible}
            onClose={closeItemSheet}
            session={apiSession}
            onItemChange={handleItemChange}
            needsClarification
            clarificationData={
              sheetTarget.clarificationData ?? { question: null, options: [] }
            }
            onClarificationResolved={(answer) =>
              void handleClarificationResolved(
                sheetTarget.eventId as string,
                sheetTarget.questionId ?? null,
                answer,
              )
            }
            editItem={editItem}
            listCandidates={listSourceCandidates}
            reResolve={reResolveItem}
            saveFood={saveFood}
          />
        ) : (
          <CorrectionSheet
            item={sheetTarget.item}
            logPhrase={sheetTarget.logPhrase}
            visible={sheetVisible}
            onClose={closeItemSheet}
            session={apiSession}
            onItemChange={handleItemChange}
            editItem={editItem}
            listCandidates={listSourceCandidates}
            reResolve={reResolveItem}
            saveFood={saveFood}
          />
        )
      ) : null}

      {/* Confirm-parsed-values sheet (FTY-197): a legible label parse is shown
          for confirm/adjust before it counts. Kept mounted while a proposal is
          set so it animates out on dismiss without the values vanishing. */}
      {apiSession && labelProposal ? (
        <ConfirmParsedValuesSheet
          item={labelProposal}
          visible={labelProposalVisible}
          session={apiSession}
          onClose={handleProposalDismissed}
          onConfirmed={handleProposalConfirmed}
          confirm={confirmLabelProposal}
        />
      ) : null}
    </>
  );
}

function Timeline({
  events,
  itemsByEvent,
  offlineStateById,
  resolveAnimIds,
  onOpenItem,
  onOpenProposal,
  onOpenClarify,
  onRetryFailed,
  onEditFailedAsText,
  phase,
  loadError,
  onRetry,
}: {
  events: readonly LogEventDTO[];
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  /** Idempotency key → offline sync state for offline-queued rows (FTY-147). */
  offlineStateById: ReadonlyMap<string, OutboxSyncState>;
  /** Event ids whose value row should ease in — the entry-resolve beat (FTY-181). */
  resolveAnimIds: ReadonlySet<string>;
  onOpenItem: (item: DerivedItem, logPhrase: string) => void;
  /** Reopen the confirm sheet for an uncounted label proposal (FTY-197). */
  onOpenProposal: (item: DerivedFoodItemDTO) => void;
  onOpenClarify: (event: LogEventDTO) => void;
  /** Retry a failed parse as a fresh attempt (FTY-176). */
  onRetryFailed: (event: LogEventDTO) => void;
  /** Prefill the composer with a failed entry's text to fix + resubmit (FTY-176). */
  onEditFailedAsText: (event: LogEventDTO) => void;
  phase: Phase;
  loadError: string | null;
  onRetry: () => void;
}) {
  const { colors } = useTheme();

  if (events.length === 0) {
    if (phase === "loading") {
      return (
        <View style={styles.state}>
          <ActivityIndicator accessibilityLabel="Loading your day" />
        </View>
      );
    }
    // An empty day still shows the hero (zeroed intake, full target available)
    // and a calm single invite — never an alarming blank.
    return (
      <View>
        {phase === "error" ? (
          <View style={styles.state}>
            <Text
              style={[styles.stateText, { color: colors.textSecondary }]}
              accessibilityRole="alert"
            >
              {loadError}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Try again"
              onPress={onRetry}
              style={styles.retry}
            >
              <Text style={[styles.retryLabel, { color: colors.text }]}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.state} testID="today-timeline-ready">
            <Text style={[styles.stateText, { color: colors.textMuted }]}>
              Log your first thing
            </Text>
          </View>
        )}
      </View>
    );
  }

  const clusters = clusterByTime(events);

  return (
    <View testID="today-timeline-with-entries">
      {phase === "error" && loadError ? (
        <Text
          style={[styles.error, { color: colors.textSecondary }]}
          accessibilityRole="alert"
        >
          {loadError}
        </Text>
      ) : null}

      {clusters.map((cluster) => (
        <ClusterView
          key={cluster.anchorTime}
          cluster={cluster}
          itemsByEvent={itemsByEvent}
          offlineStateById={offlineStateById}
          resolveAnimIds={resolveAnimIds}
          onOpenItem={onOpenItem}
          onOpenProposal={onOpenProposal}
          onOpenClarify={onOpenClarify}
          onRetryFailed={onRetryFailed}
          onEditFailedAsText={onEditFailedAsText}
          colors={colors}
        />
      ))}
    </View>
  );
}

function ClusterView({
  cluster,
  itemsByEvent,
  offlineStateById,
  resolveAnimIds,
  onOpenItem,
  onOpenProposal,
  onOpenClarify,
  onRetryFailed,
  onEditFailedAsText,
  colors,
}: {
  cluster: { anchorTime: string; events: readonly LogEventDTO[] };
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  offlineStateById: ReadonlyMap<string, OutboxSyncState>;
  resolveAnimIds: ReadonlySet<string>;
  onOpenItem: (item: DerivedItem, logPhrase: string) => void;
  onOpenProposal: (item: DerivedFoodItemDTO) => void;
  onOpenClarify: (event: LogEventDTO) => void;
  onRetryFailed: (event: LogEventDTO) => void;
  onEditFailedAsText: (event: LogEventDTO) => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.cluster}>
      <Text style={[styles.clusterTime, { color: colors.textMuted }]}>
        {formatWallClockTime(cluster.anchorTime)}
      </Text>
      <View style={[styles.card, { backgroundColor: colors.surfaceRaised }]}>
        {cluster.events.map((event) => {
          // An offline-queued capture renders through its own dedicated row —
          // never an offline branch inside EntryRow (FTY-147). It is calm,
          // uncounted, non-tappable: raw text + an explicit offline indicator.
          const offlineState = offlineStateById.get(event.id);
          if (offlineState) {
            return (
              <OfflineEntryRow
                key={event.id}
                rawText={event.raw_text}
                state={offlineState}
              />
            );
          }

          const items = itemsByEvent[event.id] ?? [];

          // Completed items are item-forward: proposed rows reopen confirm,
          // resolved rows open correction. Fresh multi-item resolves briefly
          // summarize extras until the marker clears.
          if (event.status === "completed" && items.length > 0) {
            // Beat 1 — only genuine pending→resolved counted rows animate.
            const animateResolve = resolveAnimIds.has(event.id);
            const rowTestID = itemTimelineRowTestID(event.id);
            if (animateResolve && items.length > 1) {
              const firstItem = items[0];
              if (!firstItem) return null;
              return firstItem.item_type === "food" && firstItem.status === "proposed" ? (
                <ItemTimelineRow
                  key={event.id}
                  item={firstItem}
                  proposal
                  onPress={() => onOpenProposal(firstItem)}
                  testID={rowTestID}
                />
              ) : (
                <ItemTimelineRow
                  key={event.id}
                  item={firstItem}
                  additionalItems={items.slice(1)}
                  needsClarification={false}
                  onPress={() => onOpenItem(firstItem, event.raw_text)}
                  animateResolve
                  testID={rowTestID}
                />
              );
            }
            return items.map((item, index) => {
              const key = index === 0 ? event.id : item.id;
              const testID =
                index === 0
                  ? rowTestID
                  : itemTimelineExtraRowTestID(event.id, item.id);
              return item.item_type === "food" && item.status === "proposed" ? (
                <ItemTimelineRow
                  key={key}
                  item={item}
                  proposal
                  onPress={() => onOpenProposal(item)}
                  testID={testID}
                />
              ) : (
                <ItemTimelineRow
                  key={key}
                  item={item}
                  needsClarification={false}
                  onPress={() => onOpenItem(item, event.raw_text)}
                  animateResolve={animateResolve}
                  testID={testID}
                />
              );
            });
          }

          // Optimistic / saved-food synthetic items (before the server feed
          // reports the entry). Only true local saved-food rows render here
          // (FTY-053). A server-fed by-date item is never surfaced through this
          // fallback: it can only render via the completed branch above, so a
          // resolved value row always appears on the pending→completed
          // transition that resolves the skeleton in place (FTY-180) and arms
          // beat 1 (resolve animation + haptic, FTY-181) — never un-animated
          // because the by-date feed won the poll race against the event-list
          // poll, or the event-list poll failed (FTY-181 review).
          const syntheticItems = items.filter(isSyntheticSavedFoodItem);
          if (syntheticItems.length > 0) {
            return syntheticItems.map((item) => (
              <ItemTimelineRow
                key={item.id}
                item={item}
                needsClarification={false}
                onPress={() => onOpenItem(item, event.raw_text)}
                testID={itemTimelineExtraRowTestID(event.id, item.id)}
              />
            ));
          }

          // needs_clarification → legible, inviting "needs a detail" row whose
          // tap opens the clarify-mode sheet (FTY-149).
          if (event.status === "needs_clarification") {
            return (
              <EntryRow
                key={event.id}
                event={event}
                onPress={() => onOpenClarify(event)}
              />
            );
          }

          // failed → calm, actionable "couldn't read that" row with Retry +
          // Edit as text; never a static dead-end (FTY-176).
          if (event.status === "failed") {
            return (
              <EntryRow
                key={event.id}
                event={event}
                onRetry={() => onRetryFailed(event)}
                onEditAsText={() => onEditFailedAsText(event)}
              />
            );
          }

          // pending / processing with no resolved item yet → the "thinking"
          // state: a Skeleton shimmer sized to the resolved ItemTimelineRow it
          // will become (FTY-180), so the row resolves in place with no
          // layout shift. Never the literal "Waiting"/"Estimating" text.
          if (event.status === "pending" || event.status === "processing") {
            return (
              <ItemTimelineRow
                key={event.id}
                loading
                accessibilityLabel={statusPresentation(event.status).accessibilityLabel}
                testID={itemTimelineRowTestID(event.id)}
              />
            );
          }

          // Freshly completed and still waiting on by-date items: hold the same
          // loading row. Items fade in; confirmed no-items falls through below.
          if (resolveAnimIds.has(event.id)) {
            return (
              <ItemTimelineRow
                key={event.id}
                loading
                accessibilityLabel={statusPresentation("processing").accessibilityLabel}
                testID={itemTimelineRowTestID(event.id)}
              />
            );
          }

          // completed with no items and no in-flight resolve — an entry already
          // completed on initial load, or the rare estimate that produced nothing
          // to show → terminal status placeholder, not a permanent shimmer.
          return <EntryRow key={event.id} event={event} />;
        })}
      </View>
    </View>
  );
}

function SignInRequired({ insetTop }: { insetTop: number }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.center, { paddingTop: insetTop, backgroundColor: colors.surface }]}>
      <Text style={[styles.centerTitle, { color: colors.text }]} accessibilityRole="header">
        Sign in to see your day
      </Text>
      <Text style={[styles.centerBody, { color: colors.textMuted }]}>
        Your log is stored privately against your account. Sign in to add and
        review today&apos;s food and exercise.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  content: {
    paddingHorizontal: spacing.base,
  },
  headerAction: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.sm,
    marginBottom: spacing.base,
  },
  composerActions: {
    flexDirection: "row",
    gap: spacing.xs,
    alignItems: "flex-end",
  },
  scanButton: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: spacing.md,
    fontSize: typeScale.body,
  },
  add: {
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  addLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
    color: "#FFFFFF",
  },
  error: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.md,
    marginLeft: spacing.xs,
  },
  cluster: {
    marginBottom: spacing.sm,
  },
  clusterTime: {
    fontSize: typeScale.caption1,
    fontWeight: "500",
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  card: {
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  state: {
    paddingVertical: 32,
    alignItems: "center",
    gap: spacing.base,
  },
  stateText: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    paddingHorizontal: spacing.base,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: radius.md,
  },
  retryLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "600",
  },
  center: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
  },
  centerTitle: {
    fontSize: 24,
    fontWeight: "700",
    textAlign: "center",
  },
  centerBody: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    marginTop: spacing.md,
  },
});
