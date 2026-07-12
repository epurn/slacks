import {
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
} from "@/api/corrections";
import {
  editDerivedItem as editDerivedItemApi,
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { confirmLabelProposal as confirmLabelProposalApi } from "@/api/labelProposal";
import { saveFood as saveFoodApi } from "@/api/savedFoods";
import { ConfirmParsedValuesSheet } from "@/components/ConfirmParsedValuesSheet";
import { CorrectionSheet } from "@/components/CorrectionSheet";
import { type ApiSession } from "@/state/session";

import { type SheetTarget } from "./useCorrectionSheet";

/**
 * Mounts Today's two slide-up sheets: the single reused correction/detail sheet
 * (correction on a tapped item, clarify-mode on a needs_clarification entry) and
 * the confirm-parsed-values sheet for an uncounted label proposal. Both stay
 * mounted while their target is set so they animate out cleanly. A pure view
 * host — the screen shell owns the sheet state and hands it the target + the
 * injectable API actions.
 */
export function TodaySheetHost({
  apiSession,
  sheetTarget,
  sheetVisible,
  onCloseItem,
  onItemChange,
  onClarificationResolved,
  editItem,
  listCandidates,
  reResolve,
  saveFood,
  labelProposal,
  labelProposalVisible,
  labelProposalSettledMarker,
  onProposalDismissed,
  onProposalConfirmed,
  confirmLabelProposal,
}: {
  apiSession: ApiSession | null;
  sheetTarget: SheetTarget | null;
  sheetVisible: boolean;
  onCloseItem: () => void;
  onItemChange: (item: DerivedItem) => void;
  onClarificationResolved: (
    eventId: string,
    questionId: string | null,
    answer: string,
  ) => void;
  editItem: typeof editDerivedItemApi;
  listCandidates: typeof listSourceCandidatesApi;
  reResolve: typeof reResolveItemApi;
  saveFood: typeof saveFoodApi;
  labelProposal: DerivedFoodItemDTO | null;
  labelProposalVisible: boolean;
  /**
   * The `visual-review-settled:<preset>` testID to render inside the confirm
   * sheet's own modal once it settles (FTY-262), or `null` outside the
   * `today.confirm_parsed` visual-review preset — every real launch and every
   * release build.
   */
  labelProposalSettledMarker: string | null;
  onProposalDismissed: () => void;
  onProposalConfirmed: (committed: DerivedFoodItemDTO) => void;
  confirmLabelProposal: typeof confirmLabelProposalApi;
}) {
  if (!apiSession) return null;

  return (
    <>
      {/* The single correction/detail sheet, reused for every tapped item. The
          clarify and normal forms are split so the discriminated prop contract
          (clarificationData required when needsClarification) holds at the call
          site, not just in a comment. */}
      {sheetTarget ? (
        sheetTarget.needsClarification && sheetTarget.eventId ? (
          <CorrectionSheet
            item={sheetTarget.item}
            logPhrase={sheetTarget.logPhrase}
            visible={sheetVisible}
            onClose={onCloseItem}
            session={apiSession}
            onItemChange={onItemChange}
            needsClarification
            clarificationData={
              sheetTarget.clarificationData ?? { question: null, options: [] }
            }
            onClarificationResolved={(answer) =>
              onClarificationResolved(
                sheetTarget.eventId as string,
                sheetTarget.questionId ?? null,
                answer,
              )
            }
            editItem={editItem}
            listCandidates={listCandidates}
            reResolve={reResolve}
            saveFood={saveFood}
          />
        ) : (
          <CorrectionSheet
            item={sheetTarget.item}
            logPhrase={sheetTarget.logPhrase}
            visible={sheetVisible}
            onClose={onCloseItem}
            session={apiSession}
            onItemChange={onItemChange}
            editItem={editItem}
            listCandidates={listCandidates}
            reResolve={reResolve}
            saveFood={saveFood}
            e2eInitialMode={sheetTarget.initialMode}
            settledMarkerTestID={sheetTarget.settledMarkerTestID}
            e2eExactSeed={sheetTarget.exactSeed}
            exactCapture={sheetTarget.exactCapture}
          />
        )
      ) : null}

      {/* Confirm-parsed-values sheet (FTY-197): a legible label parse is shown
          for confirm/adjust before it counts. Kept mounted while a proposal is
          set so it animates out on dismiss without the values vanishing. */}
      {labelProposal ? (
        <ConfirmParsedValuesSheet
          item={labelProposal}
          visible={labelProposalVisible}
          session={apiSession}
          onClose={onProposalDismissed}
          onConfirmed={onProposalConfirmed}
          confirm={confirmLabelProposal}
          testMarker={labelProposalSettledMarker ?? undefined}
        />
      ) : null}
    </>
  );
}
