import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import {
  getDailySummary as getDailySummaryApi,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import { getLabelProposal as getLabelProposalApi } from "@/api/labelProposal";
import { type LogEventDTO } from "@/api/logEvents";
import { isE2EMode } from "@/e2e/launchMode";
import { useVisualReviewCore } from "@/e2e/visualReview";
import { type ApiSession } from "@/state/session";
import { sortByNewest } from "@/state/today";

import {
  CONFIRM_PARSED_ITEM,
  CONFIRM_PARSED_PRESET_NAME,
  useConfirmParsedSettledMarker,
} from "./visualReviewConfirmParsed";

/**
 * Label-capture proposal flow (FTY-064 + FTY-196/197). A legible label upload
 * lands as an **uncounted proposal** the user confirms or adjusts before it
 * counts; an unreadable result has no proposal and leaves the event in place.
 * Owns the proposal state and its confirm/dismiss/reopen handlers, driving
 * Today's shared timeline/summary state through the passed setters.
 *
 * E2E-only initial-state seam (FTY-262): the `today.confirm_parsed`
 * visual-review preset has no route param to open this component-local
 * sub-state, so when that preset is the active one — and only under
 * `isE2EMode()`, so this is dead in release builds even if the runtime state
 * were somehow non-null — the proposal starts already set and visible, the
 * same shape a real legible label upload produces. No taps are simulated.
 */
export function useLabelProposal({
  apiSession,
  getLabelProposal,
  getDailySummary,
  setEvents,
  setItemsByEvent,
  setSummary,
  setSummaryError,
  setLabelCaptureOpen,
}: {
  apiSession: ApiSession | null;
  getLabelProposal: typeof getLabelProposalApi;
  getDailySummary: typeof getDailySummaryApi;
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>;
  setItemsByEvent: Dispatch<
    SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >;
  setSummary: Dispatch<SetStateAction<DailySummaryDTO | null>>;
  setSummaryError: Dispatch<SetStateAction<string | null>>;
  setLabelCaptureOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const visualReviewCore = useVisualReviewCore();
  const confirmParsedPresetActive =
    isE2EMode() && visualReviewCore.presetName === CONFIRM_PARSED_PRESET_NAME;

  // The uncounted label parse awaiting confirm/adjust (FTY-196/197). Set after a
  // legible label upload; the confirm sheet renders it and commits it — until
  // then it never counts. `null` when there is no proposal to confirm. Seeded
  // from the visual-review preset (FTY-262) on mount when that preset is active;
  // `null`/`false` otherwise, which is every real launch and every release build.
  const [labelProposal, setLabelProposal] = useState<DerivedFoodItemDTO | null>(
    () => (confirmParsedPresetActive ? CONFIRM_PARSED_ITEM : null),
  );
  const [labelProposalVisible, setLabelProposalVisible] = useState(
    () => confirmParsedPresetActive,
  );

  // The settled-marker testID for the confirm-parsed preset (FTY-262), or `null`
  // when it is not the active preset OR the sub-state has not gone network-quiet
  // yet. The shared `VisualReviewSettleOverlay` (FTY-247) renders its marker in
  // the navigator's own window, but the confirm sheet is a
  // `<Modal accessibilityViewIsModal>` — iOS accessibility restricts the
  // reachable tree to the modal's own subtree while one is presented, so the
  // shared marker is unreachable to Maestro for the whole time this sub-state is
  // up. The sheet renders this marker itself, inside its own modal, under the
  // exact same `visual-review-settled:<preset>` convention AND the same
  // network-quiet settle gate (see `useConfirmParsedSettledMarker`), so
  // screenshot automation waits for the loaded, settled frame — not the mid-load
  // one — identically to every other preset.
  const labelProposalSettledMarker = useConfirmParsedSettledMarker(
    confirmParsedPresetActive,
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
    [apiSession, getLabelProposal, setEvents, setItemsByEvent, setLabelCaptureOpen],
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
    [apiSession, getDailySummary, setItemsByEvent, setSummary, setSummaryError],
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

  return {
    labelProposal,
    labelProposalVisible,
    labelProposalSettledMarker,
    handleLabelUploaded,
    handleProposalConfirmed,
    handleProposalDismissed,
    handleReopenProposal,
  };
}
