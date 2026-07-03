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
import { type ApiSession } from "@/state/session";
import { sortByNewest } from "@/state/today";

/**
 * Label-capture proposal flow (FTY-064 + FTY-196/197). A legible label upload
 * lands as an **uncounted proposal** the user confirms or adjusts before it
 * counts; an unreadable result has no proposal and leaves the event in place.
 * Owns the proposal state and its confirm/dismiss/reopen handlers, driving
 * Today's shared timeline/summary state through the passed setters.
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
  // The uncounted label parse awaiting confirm/adjust (FTY-196/197). Set after a
  // legible label upload; the confirm sheet renders it and commits it — until
  // then it never counts. `null` when there is no proposal to confirm.
  const [labelProposal, setLabelProposal] = useState<DerivedFoodItemDTO | null>(
    null,
  );
  const [labelProposalVisible, setLabelProposalVisible] = useState(false);

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
    handleLabelUploaded,
    handleProposalConfirmed,
    handleProposalDismissed,
    handleReopenProposal,
  };
}
