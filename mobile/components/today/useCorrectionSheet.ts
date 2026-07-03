import {
  useCallback,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import { type DerivedItem } from "@/api/derivedItems";
import {
  answerClarification as answerClarificationApi,
  getLogEventClarification as getLogEventClarificationApi,
  type LogEventDTO,
} from "@/api/logEvents";
import { type ClarificationData } from "@/components/CorrectionSheet";
import { type ApiSession } from "@/state/session";
import { sortByNewest } from "@/state/today";

import { clarificationPlaceholderItem, messageFor } from "./helpers";

/**
 * The tapped correction/detail sheet target: the item plus its log phrase, and
 * — in clarify-mode — the needs_clarification event id, its (async-filled)
 * question id, and Fatty's question + quick-pick chips.
 */
export type SheetTarget = {
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
};

/**
 * The single mounted correction/detail sheet (FTY-100/148/149). Owns the sheet
 * target + visibility, opening it for a tapped item (correction) or a
 * needs_clarification entry (clarify-mode), resolving a clarification via the
 * first-class answer round-trip (FTY-170/175), and reconciling a confirmed edit
 * back into Today's item map. Drives Today's shared event/item state through the
 * passed setters.
 */
export function useCorrectionSheet({
  apiSession,
  getClarification,
  answerClarification,
  setEvents,
  setItemsByEvent,
  setSubmitError,
}: {
  apiSession: ApiSession | null;
  getClarification: typeof getLogEventClarificationApi;
  answerClarification: typeof answerClarificationApi;
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>;
  setItemsByEvent: Dispatch<
    SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >;
  setSubmitError: (message: string | null) => void;
}) {
  const [sheetTarget, setSheetTarget] = useState<SheetTarget | null>(null);
  const [sheetVisible, setSheetVisible] = useState(false);

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
      setEvents,
      setSubmitError,
    ],
  );

  // Reconcile a confirmed edit (the server's current item) back into the map,
  // replacing the prior item for its event by id so the timeline re-renders the
  // server values — including any servings-rescaled calories/macros.
  const handleItemChange = useCallback(
    (updated: DerivedItem) => {
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
    },
    [setItemsByEvent],
  );

  return {
    sheetTarget,
    sheetVisible,
    openItemSheet,
    closeItemSheet,
    openClarifySheet,
    handleClarificationResolved,
    handleItemChange,
  };
}
