import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { type DerivedItem } from "@/api/derivedItems";
import {
  createLogEvent as createLogEventApi,
  createLogEventWithImages as createLogEventWithImagesApi,
  LogEventApiError,
  type LogEventDTO,
} from "@/api/logEvents";
import { type SavedFoodDTO } from "@/api/savedFoods";
import { type OutboxStore } from "@/state/outbox";
import type { ApiSession } from "@/state/session";
import { OPTIMISTIC_ID_PREFIX, optimisticLogEvent, sortByNewest } from "@/state/today";
import { useSubmitLog, type SubmitLogBridge } from "@/state/useSubmitLog";
import { lightHaptic } from "@/utils/haptics";

import { type ComposerImage } from "./useComposerImages";
import { removeOptimisticEvent, syntheticSavedFoodItem } from "./helpers";

/**
 * The content-free marker stored for an image-only submission (no typed text),
 * mirroring the backend's `PHOTO_LOG_EVENT_RAW_TEXT` (`log-event-images.md`). It
 * seeds the optimistic row so a pending image-only entry reads sensibly if its
 * raw text is ever shown; the server returns the same marker on reconcile.
 */
const PHOTO_LOG_RAW_TEXT = "Photo log";

/** Map an image-submit failure to a calm, content-free message. */
function imageSubmitMessage(error: unknown): string {
  if (error instanceof LogEventApiError) return error.message;
  // A network-layer failure: image submissions are online-only (never queued),
  // so say so plainly rather than silently dropping the capture.
  return "Connect to the internet to add photos to a log.";
}

/** The Today-state seams the submit-bridge writes through. */
export type UseTodaySubmitParams = {
  /** The authenticated session, or null when signed out. */
  apiSession: ApiSession | null;
  /** Today's optimistic event list setter. */
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>;
  /** Today's item-by-event map setter (for the saved-food synthetic item). */
  setItemsByEvent: Dispatch<
    SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >;
  /** Injectable create endpoint for tests. */
  create: typeof createLogEventApi;
  /** Injectable multipart (text+image) create endpoint for tests (FTY-383). */
  createWithImages: typeof createLogEventWithImagesApi;
  /** Durable offline-outbox storage (FTY-104) — injectable for tests. */
  outboxStore: OutboxStore;
  /** Reconnect-retry cadence for the outbox drain — injectable for tests. */
  retryIntervalMs?: number;
  /** Idempotency-key generator — injectable for deterministic tests. */
  generateKey: () => string;
  /** Current-timestamp source — injectable for deterministic tests. */
  now: () => string;
};

/**
 * The Today submit-bridge (FTY-053/147, extracted in FTY-352). It owns the
 * saved-food selection glue that sits between Today's optimistic timeline and
 * the shared submit machine ({@link useSubmitLog}): the selected saved food and
 * its synchronous ref, the per-optimistic-id saved-food map used to re-key on
 * success / restore on rollback, and the {@link SubmitLogBridge} callbacks that
 * add the synthetic saved-food item so the estimator is skipped for a saved
 * food. `useTodayData` composes this hook and re-exposes its return surface
 * unchanged; the machine stays screen-agnostic behind the bridge.
 */
export function useTodaySubmit({
  apiSession,
  setEvents,
  setItemsByEvent,
  create,
  createWithImages,
  outboxStore,
  retryIntervalMs,
  generateKey,
  now,
}: UseTodaySubmitParams) {
  // Saved food selected from the typeahead bar (FTY-053). When set, pressing
  // "Add" creates the log event AND immediately adds a synthetic resolved item
  // with the saved food's nutrition, skipping the estimator wait.
  const [selectedSavedFood, setSelectedSavedFood] = useState<SavedFoodDTO | null>(null);

  // The submit machine reads the latest selected saved food at submit time, and
  // each in-flight submit stashes its saved food by optimistic id so the right
  // one is re-keyed on success / restored on a server-error rollback. The ref is
  // synced in an effect (never during render) per the project's ref convention.
  const selectedSavedFoodRef = useRef<SavedFoodDTO | null>(null);
  useEffect(() => {
    selectedSavedFoodRef.current = selectedSavedFood;
  });
  const pendingSavedFoodById = useRef(new Map<string, SavedFoodDTO | null>());

  // Quick-add suggestions refresh (FTY-341), called from the submit-success path
  // below. Held behind a ref so the memoized submit bridge never re-creates.
  const refreshSuggestionsRef = useRef<() => void>(() => {});

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
        // Refresh quick-add suggestions (FTY-341): the rank just changed.
        refreshSuggestionsRef.current();
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
    [apiSession, setEvents, setItemsByEvent],
  );

  const submit = useSubmitLog({
    session: apiSession,
    bridge: submitBridge,
    create,
    outboxStore,
    retryIntervalMs,
    generateKey,
    now,
  });

  // Monotonic counter for image-submit optimistic ids. Distinct suffix (`img-`)
  // so it never collides with the text machine's numeric optimistic ids, while
  // keeping the `temp-` prefix the poll reconciler recognizes.
  const imageOptimisticSeq = useRef(0);

  // Submit the current composer text together with attached images as one
  // unified multipart create (FTY-383). Online-only: it is never queued, so an
  // unreachable failure restores the composer (text is restored here; the caller
  // restores the thumbnails) and surfaces a calm message — the capture is never
  // silently dropped. Returns whether the submit succeeded so the caller knows
  // whether to restore the thumbnails.
  const { text, setText, submitting, setSubmitting, setSubmitError } = submit;
  const submitLogEntryWithImages = useCallback(
    async (images: readonly ComposerImage[], savePhoto: boolean): Promise<boolean> => {
      if (!apiSession || submitting || images.length === 0) return false;
      const trimmed = text.trim();
      const idempotencyKey = generateKey();
      const optimisticId = `${OPTIMISTIC_ID_PREFIX}img-${imageOptimisticSeq.current++}`;
      const optimistic = optimisticLogEvent({
        id: optimisticId,
        userId: apiSession.userId,
        rawText: trimmed || PHOTO_LOG_RAW_TEXT,
        createdAt: now(),
      });

      // Immediate acknowledgement: the pending row appears and the composer
      // clears (text here, thumbnails in the caller) before the round-trip.
      submitBridge.insertOptimistic(optimistic);
      setText("");
      setSubmitting(true);
      setSubmitError(null);

      try {
        const created = await createWithImages(
          apiSession,
          trimmed,
          images,
          savePhoto,
          idempotencyKey,
        );
        submitBridge.reconcileOptimistic(optimisticId, created);
        lightHaptic();
        return true;
      } catch (error) {
        submitBridge.rollbackOptimistic(optimisticId);
        setText(trimmed);
        setSubmitError(imageSubmitMessage(error));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [
      apiSession,
      submitting,
      text,
      generateKey,
      now,
      submitBridge,
      setText,
      setSubmitting,
      setSubmitError,
      createWithImages,
    ],
  );

  return {
    ...submit,
    submitLogEntryWithImages,
    selectedSavedFood,
    setSelectedSavedFood,
    selectedSavedFoodRef,
    refreshSuggestionsRef,
  };
}
