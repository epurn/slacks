import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, type TextInput } from "react-native";

import {
  type DerivedItem,
} from "@/api/derivedItems";
import {
  getDailySummary as getDailySummaryApi,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import { getLabelProposal as getLabelProposalApi } from "@/api/labelProposal";
import {
  answerClarification as answerClarificationApi,
  createLogEvent as createLogEventApi,
  getLogEventClarification as getLogEventClarificationApi,
  listTodayLogEvents as listTodayLogEventsApi,
  listTodayLogEventEntries as listTodayLogEventEntriesApi,
  type LogEventDTO,
} from "@/api/logEvents";
import { type SavedFoodDTO } from "@/api/savedFoods";
import { useCorrectionVisualReviewSeam } from "@/components/correction/visualReviewSeam";
import {
  type OutboxStore,
  type OutboxSyncState,
} from "@/state/outbox";
import { hasPendingWork, useIntervalPolling } from "@/state/polling";
import { useSession, toApiSession, type Session } from "@/state/session";
import {
  OPTIMISTIC_ID_PREFIX,
  optimisticLogEvent,
  reconcileEvents,
  sortByNewest,
} from "@/state/today";
import { useSubmitLog, type SubmitLogBridge } from "@/state/useSubmitLog";

import {
  BARCODE_MANUAL_ENTRY_SEED,
  mergeServerItems,
  messageFor,
  removeOptimisticEvent,
  syntheticSavedFoodItem,
  type Phase,
} from "./helpers";
import { useCorrectionSheet } from "./useCorrectionSheet";
import { useEntryResolveBeats } from "./useEntryResolveBeats";
import { useLabelProposal } from "./useLabelProposal";

/** The (already-resolved) inputs the Today data hook needs from the screen. */
export type UseTodayDataParams = {
  sessionOverride?: Session;
  load: typeof listTodayLogEventsApi;
  loadEntries: typeof listTodayLogEventEntriesApi;
  create: typeof createLogEventApi;
  getClarification: typeof getLogEventClarificationApi;
  answerClarification: typeof answerClarificationApi;
  itemsOverride?: Readonly<Record<string, readonly DerivedItem[]>>;
  useActive: () => boolean;
  pollIntervalMs: number;
  getLabelProposal: typeof getLabelProposalApi;
  getDailySummary: typeof getDailySummaryApi;
  outboxStore: OutboxStore;
  retryIntervalMs?: number;
  generateKey: () => string;
  now: () => string;
};

/**
 * Owns Today's data lifecycle: it loads the authenticated user's log events,
 * daily summary, and item-forward day feed; reconciles optimistic entries;
 * polls pending work to terminal; and drives the save/barcode/failed-parse
 * flows. The entry-resolve beat (FTY-181), the label-proposal flow (FTY-197),
 * and the correction/clarify sheet (FTY-148/149) live in focused sub-hooks
 * composed here. The screen shell reads the returned state and wires the
 * callbacks to the view blocks (FTY-031/032/053/147/176/180/194/198).
 */
export function useTodayData({
  sessionOverride,
  load,
  loadEntries,
  create,
  getClarification,
  answerClarification,
  itemsOverride,
  useActive,
  pollIntervalMs,
  getLabelProposal,
  getDailySummary,
  outboxStore,
  retryIntervalMs,
  generateKey,
  now,
}: UseTodayDataParams) {
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
  // Failed events the user has retried / handed to the composer this session
  // (FTY-176). This is render state only: a
  // retried failed row is superseded in place by the fresh attempt (or by the
  // composer resubmission), so it is filtered from the timeline even though the
  // server still lists the original as `failed`. A create-call error un-hides
  // the original so the failed row stays actionable — never a dead end.
  const [supersededFailedIds, setSupersededFailedIds] = useState<
    ReadonlySet<string>
  >(() => new Set());

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

  // Beat 1 — entry resolve (FTY-181): detect pending→completed transitions,
  // fire the soft-tap haptic once per resolved event, and ease the value row in.
  const { resolveAnimIds, hasFreshResolveAwaitingItems } = useEntryResolveBeats(
    events,
    phase,
    itemsByEvent,
  );

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

  // "Type it instead" from the scanner (FTY-194). The barcode surface must never
  // dead-end: dismiss the scanner and land the user in a *pre-filled*, focused
  // composer so a failed/unsupported scan flows straight into natural-language
  // logging (design §3: "Barcode not found → fall back to the NL composer
  // (pre-filled)"). The camera carries no scan data, so we seed a packaged-food
  // starter the user completes — never a fabricated number, and it counts nothing
  // until submitted. Anything the user had already typed is preserved, not
  // clobbered; only an empty composer is seeded.
  //
  // The scanner lives in a full-screen Modal that owns the keyboard/responder
  // while it is mounted, so focusing the composer synchronously — before the
  // dismissal has committed — is swallowed and the keyboard never rises. Record
  // the intent to focus and flush it once the dismissal has actually committed
  // (see `focusComposerAfterScanner`), so the fallback lands in a genuinely
  // *focused* composer rather than only a pre-filled one.
  const pendingComposerFocus = useRef(false);
  const handleManualEntry = useCallback(() => {
    if (text.trim() === "") setText(BARCODE_MANUAL_ENTRY_SEED);
    pendingComposerFocus.current = true;
    setScannerOpen(false);
  }, [setText, text]);

  // Flush a pending composer focus once the scanner Modal has actually dismissed.
  // On iOS this is driven by the Modal's `onDismiss`, which fires only after the
  // slide-out animation has fully committed and the composer can take the
  // responder. Android has no `onDismiss`, but the composer becomes focusable as
  // soon as the Modal unmounts, so the close effect below flushes it there.
  const focusComposerAfterScanner = useCallback(() => {
    if (!pendingComposerFocus.current) return;
    pendingComposerFocus.current = false;
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (Platform.OS === "ios") return; // iOS flushes from the Modal's onDismiss.
    if (!scannerOpen) focusComposerAfterScanner();
  }, [scannerOpen, focusComposerAfterScanner]);

  // Label-capture proposal flow (FTY-064 + FTY-196/197): a legible upload lands
  // as an uncounted proposal the user confirms/adjusts before it counts.
  const {
    labelProposal,
    labelProposalVisible,
    handleLabelUploaded,
    handleProposalConfirmed,
    handleProposalDismissed,
    handleReopenProposal,
  } = useLabelProposal({
    apiSession,
    getLabelProposal,
    getDailySummary,
    setEvents,
    setItemsByEvent,
    setSummary,
    setSummaryError,
    setLabelCaptureOpen,
  });

  // The single correction/detail sheet (FTY-148/149): correction on a tapped
  // item, clarify-mode on a needs_clarification entry, and the edit reconcile.
  const {
    sheetTarget,
    sheetVisible,
    openItemSheet,
    closeItemSheet,
    openClarifySheet,
    handleClarificationResolved,
    handleItemChange,
  } = useCorrectionSheet({
    apiSession,
    getClarification,
    answerClarification,
    setEvents,
    setItemsByEvent,
    setSubmitError,
  });

  // Visual-review seam (FTY-263): when a `correction.*` preset is active
  // (isE2EMode() only — always null otherwise), open the sheet directly over
  // the synthetic resolved entry in the requested mode. FTY-247 remounts this
  // whole provider subtree on every preset activation (keyed on the revision),
  // so `presetName` changing is the only re-trigger this needs — not a
  // re-render guard.
  const correctionSeam = useCorrectionVisualReviewSeam();
  useEffect(() => {
    if (!correctionSeam) return;
    openItemSheet(correctionSeam.item, correctionSeam.logPhrase, correctionSeam.mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [correctionSeam?.presetName]);

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

  return {
    session,
    apiSession,
    phase,
    loadError,
    itemsByEvent,
    displayEvents,
    offlineStateById,
    resolveAnimIds,
    summary,
    summaryError,
    scannerOpen,
    setScannerOpen,
    labelCaptureOpen,
    setLabelCaptureOpen,
    labelProposal,
    labelProposalVisible,
    sheetTarget,
    sheetVisible,
    inputRef,
    text,
    setText,
    submitting,
    submitError,
    reachability,
    queuedCount,
    setSelectedSavedFood,
    refresh,
    handleSubmit,
    handleBarcodeScanned,
    handleManualEntry,
    focusComposerAfterScanner,
    handleLabelUploaded,
    handleProposalConfirmed,
    handleProposalDismissed,
    handleReopenProposal,
    openItemSheet,
    closeItemSheet,
    openClarifySheet,
    handleClarificationResolved,
    handleRetryFailed,
    handleEditFailedAsText,
    handleItemChange,
  };
}
