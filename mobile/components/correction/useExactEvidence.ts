/**
 * FTY-312: `Make it exact` exact-evidence sub-flow state.
 *
 * Drives the correction sheet's dedicated exact-evidence surface for a low-trust
 * or incomplete food item: choose barcode or nutrition label → scan/type/capture
 * → preview what happened before anything changes → apply the proposal to the
 * **same** item in place. It owns the per-step state and the async round-trips to
 * the FTY-310 exact-evidence API client; the reusable capture surfaces
 * (`BarcodeScannerScreen` / `LabelCaptureScreen`, FTY-311) are opened as
 * full-screen modals from the panel and hand their raw barcode/label back here —
 * never creating a new log event.
 *
 * Privacy: only the barcode string, the label image URI + save flag, the opaque
 * `proposal_ref`, and an optional amount ever leave this hook (the client sends no
 * calories/macros for apply). Errors carry only content-free copy — never the
 * barcode, image, OCR text, provider output, or nutrition values.
 */

import { useCallback, useState } from "react";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import {
  applyExactEvidenceProposal as applyExactEvidenceProposalApi,
  ExactEvidenceApiError,
  ExactEvidenceEmptyBarcodeError,
  requestBarcodeExactEvidenceProposal as requestBarcodeExactEvidenceProposalApi,
  uploadLabelExactEvidenceProposal as uploadLabelExactEvidenceProposalApi,
  type ExactEvidenceProposal,
  type ExactEvidenceProposalKind,
} from "@/api/exactEvidence";
import type { LabelCapture } from "@/components/LabelCaptureScreen";
import type { ApiSession } from "@/state/session";

/** The applyable proposal outcomes the preview renders (never a `none` read). */
export type ApplyableProposal = Extract<
  ExactEvidenceProposal,
  { quality: "exact" | "fallback" }
>;

/**
 * Which evidence attempt produced the current loading/error/preview, so
 * `Try again` re-opens the right capture surface (re-scan, re-type, re-photo).
 */
type EvidenceAttempt = "barcode-typed" | "barcode-scanned" | "label";

/**
 * The panel's current step:
 * - `choose` — the barcode-or-label choice surface;
 * - `type-barcode` — the typed-barcode entry field;
 * - `loading` — a proposal request is in flight;
 * - `preview` — an applyable exact/fallback proposal is shown for confirm;
 * - `error` — a no-proposal/network/API failure, item unchanged.
 */
export type ExactStep = "choose" | "type-barcode" | "loading" | "preview" | "error";

/** Map an exact-evidence failure to plain, content-free copy for the panel. */
function messageForExactError(err: unknown): string {
  if (
    err instanceof ExactEvidenceApiError ||
    err instanceof ExactEvidenceEmptyBarcodeError
  ) {
    return err.message;
  }
  return "We couldn't do that. Check your connection and try again.";
}

/** Fallback banner copy: honest that exact evidence failed, never labelled exact. */
export function fallbackNotice(kind: ExactEvidenceProposalKind): string {
  return kind === "barcode"
    ? "No exact match from that barcode. This is the best rough fallback."
    : "We couldn't read exact facts from that label. This is the best rough fallback.";
}

/** No-proposal copy: nothing applyable, with the paths back the user always has. */
function noProposalNotice(kind: ExactEvidenceProposalKind): string {
  return kind === "barcode"
    ? "No exact match from that barcode, and no rough fallback either. Try again, change the match, or edit it manually."
    : "We couldn't read that label, and no rough fallback either. Try again, change the match, or edit it manually.";
}

export interface UseExactEvidenceArgs {
  session: ApiSession;
  item: DerivedFoodItemDTO;
  /** True while the sheet is in `make-exact` mode; resets the sub-flow on entry. */
  active: boolean;
  /** Commit an applied proposal to the same item in place (fires the saved beat). */
  onCommitted: (updated: DerivedFoodItemDTO) => void;
  /** Injectable FTY-310 clients (tests supply mocks). */
  requestBarcodeProposal?: typeof requestBarcodeExactEvidenceProposalApi;
  uploadLabelProposal?: typeof uploadLabelExactEvidenceProposalApi;
  applyProposal?: typeof applyExactEvidenceProposalApi;
}

export function useExactEvidence({
  session,
  item,
  active,
  onCommitted,
  requestBarcodeProposal = requestBarcodeExactEvidenceProposalApi,
  uploadLabelProposal = uploadLabelExactEvidenceProposalApi,
  applyProposal = applyExactEvidenceProposalApi,
}: UseExactEvidenceArgs) {
  const [step, setStep] = useState<ExactStep>("choose");
  const [barcodeText, setBarcodeText] = useState("");
  const [proposal, setProposal] = useState<ApplyableProposal | null>(null);
  // Preview amount — always concrete in the preview (a proposal that can't cost
  // the current amount still needs one to apply), so the stepper/apply never
  // guess a silent portion.
  const [amount, setAmount] = useState<number>(1);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<EvidenceAttempt | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [labelOpen, setLabelOpen] = useState(false);
  const [applying, setApplying] = useState(false);

  // Reset the whole sub-flow when the sheet enters make-exact mode (false→true),
  // using the render-time "adjust state on prop change" pattern (no effect) that
  // the rest of the correction sheet uses.
  const [prevActive, setPrevActive] = useState(active);
  if (active !== prevActive) {
    setPrevActive(active);
    if (active) {
      setStep("choose");
      setBarcodeText("");
      setProposal(null);
      setError(null);
      setAttempt(null);
      setScannerOpen(false);
      setLabelOpen(false);
      setApplying(false);
    }
  }

  // Resolve a proposal promise into the preview / error step. Never rejects — a
  // failed request lands on the error step with content-free copy, item untouched.
  const handleProposal = useCallback(
    async (source: EvidenceAttempt, promise: Promise<ExactEvidenceProposal>) => {
      setAttempt(source);
      setStep("loading");
      setError(null);
      try {
        const result = await promise;
        if (result.quality === "none") {
          setError(noProposalNotice(result.kind));
          setStep("error");
          return;
        }
        setProposal(result);
        setAmount(result.preview.amount ?? item.amount ?? 1);
        setStep("preview");
      } catch (err) {
        setError(messageForExactError(err));
        setStep("error");
      }
    },
    [item.amount],
  );

  // ─── Choice surface ──────────────────────────────────────────────────────────

  const chooseTypeBarcode = useCallback(() => {
    setError(null);
    setBarcodeText("");
    setStep("type-barcode");
  }, []);

  const chooseScanBarcode = useCallback(() => {
    setError(null);
    setScannerOpen(true);
  }, []);

  const chooseCaptureLabel = useCallback(() => {
    setError(null);
    setLabelOpen(true);
  }, []);

  const backToChoose = useCallback(() => {
    setStep("choose");
    setError(null);
    setProposal(null);
    setBarcodeText("");
  }, []);

  // ─── Evidence submission ─────────────────────────────────────────────────────

  const submitTypedBarcode = useCallback(() => {
    const trimmed = barcodeText.trim();
    if (trimmed.length === 0) {
      // Keep the user on the entry field with an inline nudge — no network call.
      setError("Enter a barcode to look up.");
      return;
    }
    setError(null);
    void handleProposal(
      "barcode-typed",
      requestBarcodeProposal(session, item.id, trimmed),
    );
  }, [barcodeText, handleProposal, requestBarcodeProposal, session, item.id]);

  // The scanner hands back a raw barcode string; close it and request a proposal
  // (never a new log event).
  const handleBarcodeScanned = useCallback(
    (barcode: string) => {
      setScannerOpen(false);
      void handleProposal(
        "barcode-scanned",
        requestBarcodeProposal(session, item.id, barcode),
      );
    },
    [handleProposal, requestBarcodeProposal, session, item.id],
  );

  // The label capture hands back the image URI + save flag; close it and request
  // a label proposal (no new log event, no normal label-proposal row). Resolves
  // (never rejects) so the capture surface never shows its own error over ours.
  const handleLabelSubmit = useCallback(
    async ({ imageUri, savePhoto }: LabelCapture) => {
      setLabelOpen(false);
      await handleProposal(
        "label",
        uploadLabelProposal(session, item.id, imageUri, savePhoto),
      );
    },
    [handleProposal, uploadLabelProposal, session, item.id],
  );

  // ─── Preview interactions ────────────────────────────────────────────────────

  const stepAmount = useCallback((delta: number) => {
    setAmount((prev) => Math.max(0.25, Math.round((prev + delta) * 4) / 4));
  }, []);

  // Apply the previewed proposal in place. Sends only the opaque ref and an
  // optional amount — the client can never inject nutrition facts. The amount is
  // sent when the user changed it, or when the source can't cost the current
  // amount (apply then requires an explicit one); otherwise omitted to keep the
  // current portion.
  const apply = useCallback(async () => {
    if (!proposal) return;
    const sendAmount =
      !proposal.can_cost_current_amount || amount !== item.amount
        ? amount
        : undefined;
    setApplying(true);
    setError(null);
    try {
      const updated = await applyProposal(
        session,
        item.id,
        proposal.proposal_ref,
        sendAmount,
      );
      onCommitted(updated);
    } catch (err) {
      // Stay on the preview with a content-free banner; the item is unchanged.
      setError(messageForExactError(err));
    } finally {
      setApplying(false);
    }
  }, [proposal, amount, item.amount, item.id, applyProposal, session, onCommitted]);

  // Re-attempt the same evidence kind that produced the current preview/error:
  // re-open the scanner / label capture, or return to the barcode field.
  const tryAgain = useCallback(() => {
    setError(null);
    setProposal(null);
    if (attempt === "barcode-scanned") {
      setScannerOpen(true);
    } else if (attempt === "label") {
      setLabelOpen(true);
    } else {
      // typed barcode (or unknown) → back to the entry field, text retained.
      setStep("type-barcode");
    }
  }, [attempt]);

  const closeScanner = useCallback(() => setScannerOpen(false), []);
  const closeLabel = useCallback(() => setLabelOpen(false), []);

  return {
    step,
    barcodeText,
    setBarcodeText,
    proposal,
    amount,
    error,
    scannerOpen,
    labelOpen,
    applying,
    chooseTypeBarcode,
    chooseScanBarcode,
    chooseCaptureLabel,
    backToChoose,
    submitTypedBarcode,
    handleBarcodeScanned,
    handleLabelSubmit,
    stepAmount,
    apply,
    tryAgain,
    closeScanner,
    closeLabel,
  };
}
