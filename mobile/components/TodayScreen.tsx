import { useCallback, useState } from "react";
import {
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
} from "@/api/corrections";
import {
  editDerivedItem as editDerivedItemApi,
  type DerivedItem,
} from "@/api/derivedItems";
import { getDailySummary as getDailySummaryApi } from "@/api/dailySummary";
import { getFoodSuggestions as getFoodSuggestionsApi } from "@/api/foodSuggestions";
import { uploadLabelImage as uploadLabelImageApi } from "@/api/labelCapture";
import {
  confirmLabelProposal as confirmLabelProposalApi,
  getLabelProposal as getLabelProposalApi,
} from "@/api/labelProposal";
import {
  answerClarification as answerClarificationApi,
  createLogEvent as createLogEventApi,
  createLogEventWithImages as createLogEventWithImagesApi,
  deleteLogEvent as deleteLogEventApi,
  getLogEventClarification as getLogEventClarificationApi,
  listTodayLogEvents as listTodayLogEventsApi,
  listTodayLogEventEntries as listTodayLogEventEntriesApi,
} from "@/api/logEvents";
import {
  saveFood as saveFoodApi,
  searchSavedFoods as searchSavedFoodsApi,
} from "@/api/savedFoods";
import {
  AppIcon,
  ScreenHeader,
  floatingSwitcherClearance,
} from "@/components/ui";
import { BarcodeScannerScreen } from "@/components/BarcodeScannerScreen";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { DailySummary } from "@/components/DailySummary";
import { LabelCaptureScreen } from "@/components/LabelCaptureScreen";
import { MacroTier } from "@/components/MacroTier";
import { QuickAddChips } from "@/components/today/QuickAddChips";
import { Timeline } from "@/components/today/Timeline";
import { SignInRequired } from "@/components/today/SignInRequired";
import { TodayComposer } from "@/components/today/TodayComposer";
import { TodaySheetHost } from "@/components/today/TodaySheetHost";
import { type ComposerImagePickers } from "@/components/today/useComposerImages";
import { useTodayData } from "@/components/today/useTodayData";
import { VisualReviewSettleOverlay } from "@/e2e/visualReview";
import { generateIdempotencyKey, type OutboxStore } from "@/state/outbox";
import { fileOutboxStore } from "@/state/outboxStore";
import { POLL_INTERVAL_MS } from "@/state/polling";
import { type Session } from "@/state/session";
import { useScreenActive } from "@/state/useScreenActive";
import { useTheme, spacing } from "@/theme";

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
 * The data lifecycle — load/poll `Phase` state, optimistic-event reconciliation,
 * the save/clarify/label/barcode flows, and the signature beats — lives in
 * `useTodayData`; this shell wires that state to the view blocks (`Timeline`,
 * `SignInRequired`) and the sheets/modals. `load`/`create`/`session`/`useActive`/
 * `pollIntervalMs` and friends are injectable for tests.
 *
 * Until the mobile sign-in flow lands (a separate story) there is no session on
 * the device, so this renders a clear "sign in" state, mirroring the profile
 * capture flow.
 */
export function TodayScreen({
  session: sessionOverride,
  load = listTodayLogEventsApi,
  loadEntries = listTodayLogEventEntriesApi,
  create = createLogEventApi,
  createWithImages = createLogEventWithImagesApi,
  deleteEvent = deleteLogEventApi,
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
  getSuggestions = getFoodSuggestionsApi,
  outboxStore = fileOutboxStore,
  retryIntervalMs,
  generateKey = generateIdempotencyKey,
  now = () => new Date().toISOString(),
  composerImagePickers,
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
  /** Injectable multipart (text+image) create for the composer attach flow (FTY-383). */
  createWithImages?: typeof createLogEventWithImagesApi;
  /** Injectable soft-void (delete) client for swipe-to-delete (FTY-322). */
  deleteEvent?: typeof deleteLogEventApi;
  /** Injectable clarification-question read for the clarify sheet (FTY-153). */
  getClarification?: typeof getLogEventClarificationApi;
  /** Injectable clarification answer round-trip for the clarify sheet (FTY-170/175). */
  answerClarification?: typeof answerClarificationApi;
  editItem?: typeof editDerivedItemApi;
  /**
   * Derived food/exercise items keyed by their `log_event_id`, rendered as
   * `ItemTimelineRow`s that open the correction sheet on press (FTY-050). Seeds
   * the map; the item-forward by-date feed (`loadEntries`, FTY-198) folds real
   * server items in as events reach `completed`, and edits reconcile the
   * server's returned item back into this map.
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
  /** Injectable quick-add suggestions fetch for tests (FTY-341). */
  getSuggestions?: typeof getFoodSuggestionsApi;
  /** Durable offline-outbox storage (FTY-104, harvested onto Today in FTY-147). */
  outboxStore?: OutboxStore;
  /** Reconnect-retry cadence for the outbox drain — injectable for tests. */
  retryIntervalMs?: number;
  /** Idempotency-key generator — injectable for deterministic tests. */
  generateKey?: () => string;
  /** Capture-timestamp source — injectable for deterministic tests. */
  now?: () => string;
  /** Injectable composer image pickers (FTY-383) — tests/E2E override the OS picker. */
  composerImagePickers?: Partial<ComposerImagePickers>;
  /** Called when the user presses the gear / profile icon in the header. */
  onPressProfile?: () => void;
} = {}) {
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();

  const {
    session,
    apiSession,
    phase,
    loadError,
    deleteError,
    itemsByEvent,
    questionsByEvent,
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
    labelProposalSettledMarker,
    sheetTarget,
    sheetVisible,
    inputRef,
    text,
    setText,
    handleComposerTextChange,
    submitting,
    submitError,
    reachability,
    queuedCount,
    composerImages,
    attachComposerImage,
    removeComposerImage,
    composerAttachError,
    attachDisabled,
    setSelectedSavedFood,
    suggestions,
    handleSelectSuggestion,
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
    handleDeleteEvent,
    handleItemChange,
  } = useTodayData({
    sessionOverride,
    load,
    loadEntries,
    create,
    createWithImages,
    deleteEvent,
    getClarification,
    answerClarification,
    itemsOverride,
    useActive,
    pollIntervalMs,
    getLabelProposal,
    getDailySummary,
    getSuggestions,
    searchSavedFoods,
    outboxStore,
    retryIntervalMs,
    generateKey,
    now,
    composerImagePickers,
  });

  // Pull-to-refresh (FTY-185): the standard iOS `RefreshControl` idiom replaces
  // the old header refresh button. It reuses the existing `refresh` handler —
  // only the trigger changes. The platform spinner should track a *pull*, not
  // every load (the initial fetch and summary/timeline retries also drive
  // `phase === "loading"`), so `refreshing` is its own state set on pull and
  // cleared the moment that load settles. Clearing happens by adjusting state
  // during render off a tracked phase transition (React's documented
  // alternative to a setState-in-effect), not from an effect.
  const [refreshing, setRefreshing] = useState(false);
  const [trackedPhase, setTrackedPhase] = useState(phase);
  if (phase !== trackedPhase) {
    setTrackedPhase(phase);
    if (refreshing && phase !== "loading") {
      setRefreshing(false);
    }
  }
  const onPullToRefresh = useCallback(() => {
    setRefreshing(true);
    refresh();
  }, [refresh]);

  if (!session) {
    return <SignInRequired insetTop={insets.top + 24} />;
  }

  // At least one surface (FTY-374): typed text OR an attached photo enables Add.
  const canSubmit = (text.trim() !== "" || composerImages.length > 0) && !submitting;

  return (
    <>
      <Modal
        visible={scannerOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setScannerOpen(false)}
        onDismiss={focusComposerAfterScanner}
      >
        <BarcodeScannerScreen
          onBarcodeScanned={(barcode) => void handleBarcodeScanned(barcode)}
          onClose={() => setScannerOpen(false)}
          onManualEntry={handleManualEntry}
        />
        {/* Visual-review settled marker (FTY-268): the scanner is a full-screen
            native Modal, which on iOS is a separate presented context from the
            screen behind it, so the shared root-level marker (app/_layout.tsx)
            is not reliably reachable while this is up top. Mounting the same
            component here (unmodified, just imported) exposes the marker in the
            presented context that's actually visible; it self-gates to
            isE2EMode() and renders nothing in every other build/state. */}
        <VisualReviewSettleOverlay />
      </Modal>

      <Modal
        visible={labelCaptureOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setLabelCaptureOpen(false)}
      >
        {apiSession && (
          <LabelCaptureScreen
            onClose={() => setLabelCaptureOpen(false)}
            onSubmit={async ({ imageUri, savePhoto }) => {
              // Normal Today path: upload via uploadLabelImage, then open the
              // confirm-parsed-values flow with the returned label event.
              const event = await uploadLabel(apiSession, imageUri, savePhoto);
              handleLabelUploaded(event);
            }}
            takePhoto={labelTakePhoto}
          />
        )}
        {/* Same rationale as the scanner Modal above. */}
        <VisualReviewSettleOverlay />
      </Modal>

      <ScrollView
        testID="today-screen"
        style={[styles.screen, { backgroundColor: colors.surface }]}
        contentContainerStyle={[
          styles.content,
          // The floating switcher (FTY-242) is absolutely positioned and
          // overlays the scroll content, so the last entry needs clearance
          // beyond the safe area for its whole footprint. Sourced from the
          // shared inset so Today can't drift from the pill's real geometry.
          { paddingBottom: floatingSwitcherClearance(insets.bottom) },
        ]}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onPullToRefresh}
            // VoiceOver reads the native refresh state; the label names the
            // action for the pull gesture and the spinner.
            accessibilityLabel="Refresh today"
          />
        }
      >
        <ScreenHeader
          title="Today"
          actions={
            // Refresh moved to a standard pull-to-refresh `RefreshControl` on the
            // timeline (FTY-185) — the header no longer carries a manual-refresh
            // button, keeping the dashboard chrome calm.
            onPressProfile ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Open profile"
                accessibilityHint="Opens profile and settings"
                onPress={onPressProfile}
                style={styles.headerAction}
              >
                <AppIcon name="gear" size={22} color={colors.text} />
              </Pressable>
            ) : null
          }
        />

        {/* Calm connection banner between header and composer; self-hides when
            online and caught up (FTY-104, harvested onto Today in FTY-147). */}
        <ConnectionBanner state={reachability} queuedCount={queuedCount} />

        {/* Hero first, composer directly beneath it (FTY-178 Q-A1 default);
            the macro tier renders below the composer — reworking it is FTY-179. */}
        <DailySummary summary={summary} error={summaryError} onRetry={refresh} showMacros={false} />

        {/* Quick-add suggestion chips (FTY-341): a calm, scrollable row of what
            the user most plausibly wants to log now, above the composer. Renders
            nothing when there is nothing to suggest — no empty shell. */}
        <QuickAddChips suggestions={suggestions} onSelect={handleSelectSuggestion} />

        <TodayComposer
          inputRef={inputRef}
          text={text}
          onChangeText={handleComposerTextChange}
          submitting={submitting}
          canSubmit={canSubmit}
          apiSession={apiSession}
          searchSavedFoods={searchSavedFoods}
          onSelectSavedFood={(food) => {
            setSelectedSavedFood(food);
            setText(food.name);
          }}
          suggestions={suggestions}
          onSelectSuggestion={handleSelectSuggestion}
          onScan={() => setScannerOpen(true)}
          onCaptureLabel={() => setLabelCaptureOpen(true)}
          onSubmit={() => void handleSubmit()}
          submitError={submitError}
          images={composerImages}
          onAttach={() => void attachComposerImage()}
          onRemoveImage={removeComposerImage}
          attachDisabled={attachDisabled}
          attachError={composerAttachError}
        />

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
          questionsByEvent={questionsByEvent}
          offlineStateById={offlineStateById}
          resolveAnimIds={resolveAnimIds}
          onOpenItem={openItemSheet}
          onOpenProposal={handleReopenProposal}
          onOpenClarify={openClarifySheet}
          onRetryFailed={(event) => void handleRetryFailed(event)}
          onEditFailedAsText={handleEditFailedAsText}
          onDeleteEvent={(event) => void handleDeleteEvent(event)}
          phase={phase}
          loadError={loadError}
          deleteError={deleteError}
          onRetry={() => void refresh()}
        />
      </ScrollView>

      <TodaySheetHost
        apiSession={apiSession}
        sheetTarget={sheetTarget}
        sheetVisible={sheetVisible}
        onCloseItem={closeItemSheet}
        onItemChange={handleItemChange}
        onClarificationResolved={handleClarificationResolved}
        editItem={editItem}
        listCandidates={listSourceCandidates}
        reResolve={reResolveItem}
        saveFood={saveFood}
        labelProposal={labelProposal}
        labelProposalVisible={labelProposalVisible}
        labelProposalSettledMarker={labelProposalSettledMarker}
        onProposalDismissed={handleProposalDismissed}
        onProposalConfirmed={handleProposalConfirmed}
        confirmLabelProposal={confirmLabelProposal}
      />
    </>
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
});
