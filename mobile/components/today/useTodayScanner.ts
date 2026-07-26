import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { Platform, type TextInput } from "react-native";

import {
  createLogEvent as createLogEventApi,
  type LogEventDTO,
} from "@/api/logEvents";
import type { ApiSession } from "@/state/session";
import {
  OPTIMISTIC_ID_PREFIX,
  optimisticLogEvent,
  sortByNewest,
} from "@/state/today";

import {
  CAPTURE_BARCODE_GRANTED_PRESET,
  CAPTURE_LABEL_AUTO_UPLOAD_PRESET,
  CAPTURE_LABEL_GUIDANCE_PRESET,
  type CaptureVisualReviewPreset,
} from "./captureVisualReview";
import { BARCODE_MANUAL_ENTRY_SEED, messageFor } from "./helpers";

/** The Today seams the scanner / manual-entry / composer-focus block reads. */
export type UseTodayScannerParams = {
  /** The authenticated session, or null when signed out. */
  apiSession: ApiSession | null;
  /** Active capture preset (E2E-only), used to seed the initial modal state. */
  activeCapturePreset: CaptureVisualReviewPreset;
  /** True while a composer submit is in flight (blocks a racing barcode scan). */
  submitting: boolean;
  /** Injectable create endpoint for tests. */
  create: typeof createLogEventApi;
  /** The composer text, so an existing draft is preserved on manual fallback. */
  text: string;
  /** Composer text setter (seeds the packaged-food starter on fallback). */
  setText: (next: string) => void;
  /** In-flight submit flag setter (guards the barcode optimistic round-trip). */
  setSubmitting: (next: boolean) => void;
  /** Submit-error setter shown beside the composer. */
  setSubmitError: (next: string | null) => void;
  /** Today's optimistic event list setter. */
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>;
  /** Monotonic optimistic-id counter, shared with the failed-retry path. */
  tempIdRef: MutableRefObject<number>;
  /** Composer input handle so the manual fallback lands in a focused composer. */
  inputRef: MutableRefObject<TextInput | null>;
};

/**
 * The Today scanner / manual-entry / composer-focus block (FTY-063/194,
 * extracted in FTY-352). It owns the barcode-scanner and label-capture modal
 * visibility, the barcode scan submit (mirroring the composer's optimistic
 * insert → reconcile → rollback), and the "type it instead" fallback that
 * pre-fills and focuses the composer once the scanner Modal has dismissed.
 * `useTodayData` composes this hook and re-exposes its surface unchanged.
 */
export function useTodayScanner({
  apiSession,
  activeCapturePreset,
  submitting,
  create,
  text,
  setText,
  setSubmitting,
  setSubmitError,
  setEvents,
  tempIdRef,
  inputRef,
}: UseTodayScannerParams) {
  // Visual-review capture seam (FTY-268): reads only under isE2EMode() (see
  // captureVisualReview.ts) and is inert — always null — outside it, so a
  // release build's initial scannerOpen/labelCaptureOpen are always false,
  // unchanged from before this seam existed.
  const [scannerOpen, setScannerOpen] = useState(
    () => activeCapturePreset === CAPTURE_BARCODE_GRANTED_PRESET,
  );
  const [labelCaptureOpen, setLabelCaptureOpen] = useState(
    () =>
      activeCapturePreset === CAPTURE_LABEL_GUIDANCE_PRESET ||
      // FTY-433: the auto-upload preset opens the same surface, then drives the
      // real shutter → upload → confirm path through its capture seams.
      activeCapturePreset === CAPTURE_LABEL_AUTO_UPLOAD_PRESET,
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
      const id = `${OPTIMISTIC_ID_PREFIX}${tempIdRef.current++}`;
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
    [apiSession, submitting, create, setSubmitting, setSubmitError, setEvents, tempIdRef],
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
  }, [inputRef]);

  useEffect(() => {
    if (Platform.OS === "ios") return; // iOS flushes from the Modal's onDismiss.
    if (!scannerOpen) focusComposerAfterScanner();
  }, [scannerOpen, focusComposerAfterScanner]);

  return {
    scannerOpen,
    setScannerOpen,
    labelCaptureOpen,
    setLabelCaptureOpen,
    handleBarcodeScanned,
    handleManualEntry,
    focusComposerAfterScanner,
  };
}
