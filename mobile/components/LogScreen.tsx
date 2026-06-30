import {
  AccessibilityInfo,
  Animated,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  createLogEvent as createLogEventApi,
  listTodayLogEvents as listTodayLogEventsApi,
  LogEventApiError,
  type LogEventDTO,
} from "@/api/logEvents";
import { uploadLabelImage as uploadLabelImageApi } from "@/api/labelCapture";
import {
  searchSavedFoods as searchSavedFoodsApi,
  type SavedFoodDTO,
} from "@/api/savedFoods";
import { BarcodeScannerScreen } from "@/components/BarcodeScannerScreen";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { LabelCaptureScreen } from "@/components/LabelCaptureScreen";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import { AppIcon, Skeleton } from "@/components/ui";
import {
  POLL_INTERVAL_MS,
  hasPendingWork,
  isNonTerminal,
  useIntervalPolling,
} from "@/state/polling";
import {
  createOutboxEntry,
  generateIdempotencyKey,
  pendingCount,
  type OutboxEntry,
  type OutboxStore,
  type OutboxSubmit,
  type OutboxSyncState,
} from "@/state/outbox";
import { fileOutboxStore } from "@/state/outboxStore";
import { isUnreachableError } from "@/state/reachability";
import { useOfflineQueue } from "@/state/useOfflineQueue";
import {
  OPTIMISTIC_ID_PREFIX,
  optimisticLogEvent,
  statusPresentation,
} from "@/state/today";
import {
  useSession,
  toApiSession,
  type Session,
} from "@/state/session";
import { useScreenActive } from "@/state/useScreenActive";
import {
  gentleSpring,
  radius,
  reducedMotionDuration,
  spacing,
  typeScale,
  useTheme,
} from "@/theme";

const MAX_RAW_TEXT_LENGTH = 2000;

/**
 * Fixed height for every feed row — skeleton and resolved content occupy the
 * same footprint so the layout never shifts when the status changes.
 */
const FEED_ROW_HEIGHT = 60;

/** One entry in the transient added-this-session feed. */
interface FeedEntry {
  /** Stable key for React lists (optimistic id until the server confirms). */
  key: string;
  event: LogEventDTO;
  /**
   * When a saved-food suggestion was applied, the stored nutrition is available
   * immediately (estimator bypassed). The FeedRow renders it without waiting for
   * polling.
   */
  savedFood: SavedFoodDTO | null;
  /**
   * Present iff this row is an offline-queued capture (FTY-104) that has not yet
   * reached the server. It carries the local sync state so the row shows the
   * right calm offline indicator. Online rows leave this undefined.
   */
  offline?: OutboxSyncState;
}

function messageFor(error: unknown): string {
  if (error instanceof LogEventApiError) {
    return error.message;
  }
  return "We couldn't save that entry. Please try again.";
}

/**
 * The Log page (FTY-099): a keyboard-up natural-language composer with a
 * reactive saved-food typeahead, barcode and label capture affordances, and a
 * transient added-this-session feed.
 *
 * On submit the page stays on Log — no navigation — the input clears, and the
 * entry joins the feed. While the backend estimates an entry, a skeleton/shimmer
 * placeholder fills the row; resolved values fade in in the same slot (no
 * layout shift). Returning to Today is a manual, user-initiated action.
 *
 * `create`, `poll`, `searchSavedFoods`, `uploadLabel`, `useActive`, and
 * `pollIntervalMs` are injectable for tests (no real network call needed).
 */
export function LogScreen({
  session: sessionOverride,
  create = createLogEventApi,
  poll = listTodayLogEventsApi,
  searchSavedFoods = searchSavedFoodsApi,
  uploadLabel = uploadLabelImageApi,
  labelTakePhoto,
  useActive = useScreenActive,
  pollIntervalMs = POLL_INTERVAL_MS,
  outboxStore = fileOutboxStore,
  retryIntervalMs,
  generateKey = generateIdempotencyKey,
  now = () => new Date().toISOString(),
}: {
  session?: Session;
  create?: typeof createLogEventApi;
  /** Injectable poll function for tests — defaults to listTodayLogEvents. */
  poll?: typeof listTodayLogEventsApi;
  searchSavedFoods?: typeof searchSavedFoodsApi;
  uploadLabel?: typeof uploadLabelImageApi;
  labelTakePhoto?: () => Promise<{ uri: string }>;
  useActive?: () => boolean;
  pollIntervalMs?: number;
  /** Durable offline-outbox storage (FTY-104) — injectable for tests. */
  outboxStore?: OutboxStore;
  /** Reconnect-retry cadence for the outbox drain — injectable for tests. */
  retryIntervalMs?: number;
  /** Idempotency-key generator — injectable for deterministic tests. */
  generateKey?: () => string;
  /** Capture-timestamp source — injectable for deterministic tests. */
  now?: () => string;
} = {}) {
  const insets = useSafeAreaInsets();
  const { colors } = useTheme();
  const liveSession = useSession();
  const session = sessionOverride !== undefined ? sessionOverride : liveSession;
  const apiSession = useMemo(
    () => (session ? toApiSession(session) : null),
    [session],
  );

  const [feed, setFeed] = useState<readonly FeedEntry[]>([]);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [selectedSavedFood, setSelectedSavedFood] = useState<SavedFoodDTO | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [labelCaptureOpen, setLabelCaptureOpen] = useState(false);
  const tempId = useRef(0);

  // ── Offline outbox (FTY-104) ────────────────────────────────────────────────
  // When an offline-queued entry is accepted on reconnect, fold the real server
  // event into the feed (replacing any leftover optimistic row for its key) so it
  // follows the normal server-driven pending → resolved flow and begins counting.
  const handleAccepted = useCallback(
    (entry: OutboxEntry, event: LogEventDTO) => {
      setFeed((prev) => [
        { key: event.id, event, savedFood: null },
        ...prev.filter(
          (f) => f.key !== entry.idempotencyKey && f.key !== event.id,
        ),
      ]);
    },
    [],
  );

  const queueSubmit = useCallback<OutboxSubmit>(
    (entry) => {
      if (!apiSession) {
        return Promise.reject(new Error("No session for outbox submit."));
      }
      return create(apiSession, entry.rawText, entry.idempotencyKey);
    },
    [apiSession, create],
  );

  const {
    reachability,
    entries: outboxEntries,
    enqueue,
    drainNow,
  } = useOfflineQueue({
    userId: apiSession?.userId ?? null,
    submit: queueSubmit,
    store: outboxStore,
    onAccepted: handleAccepted,
    retryIntervalMs,
  });

  // Poll while any feed entry is non-terminal and the screen is active.
  const pollOnce = useCallback(() => {
    if (!apiSession) return;
    void poll(apiSession).then(
      (serverEvents) => {
        const byId = new Map(serverEvents.map((e) => [e.id, e]));
        setFeed((prev) =>
          prev.map((entry) => {
            if (!isNonTerminal(entry.event.status)) return entry;
            const updated = byId.get(entry.event.id);
            return updated ? { ...entry, event: updated } : entry;
          }),
        );
      },
      () => {
        // Swallow transient poll errors; retry on the next tick.
      },
    );
  }, [apiSession, poll]);

  const isActive = useActive();
  const feedEvents = useMemo(() => feed.map((e) => e.event), [feed]);
  const shouldPoll = isActive && hasPendingWork(feedEvents);
  useIntervalPolling(shouldPoll, pollIntervalMs, pollOnce);

  // Offline-queued entries render as calm offline-pending rows alongside the
  // online feed. They are uncounted and carry no fabricated number.
  const offlineRows = useMemo<readonly FeedEntry[]>(
    () =>
      outboxEntries
        .filter((e) => e.syncState !== "accepted")
        .map((e) => ({
          key: e.idempotencyKey,
          event: optimisticLogEvent({
            id: e.idempotencyKey,
            userId: e.userId,
            rawText: e.rawText,
            createdAt: e.capturedAt,
          }),
          savedFood: null,
          offline: e.syncState,
        })),
    [outboxEntries],
  );

  // One newest-first list: online optimistic/resolved rows plus offline rows.
  const rows = useMemo<readonly FeedEntry[]>(
    () =>
      [...feed, ...offlineRows].sort((a, b) =>
        b.event.created_at.localeCompare(a.event.created_at),
      ),
    [feed, offlineRows],
  );

  const queuedCount = pendingCount(outboxEntries);

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || !apiSession || submitting) return;

    // The idempotency key is minted once, here, and reused on every retry — that
    // is what makes a reconnect drain of this entry dedup-safe (FTY-104).
    const idempotencyKey = generateKey();
    const capturedAt = now();
    const pendingSavedFood = selectedSavedFood;
    setSelectedSavedFood(null);

    const optimistic = optimisticLogEvent({
      id: idempotencyKey,
      userId: apiSession.userId,
      rawText: trimmed,
      createdAt: capturedAt,
    });

    setFeed((prev) => [
      { key: idempotencyKey, event: optimistic, savedFood: pendingSavedFood },
      ...prev,
    ]);
    // Clear the composer immediately so the next entry can be typed at once.
    setText("");
    setSubmitting(true);
    setSubmitError(null);

    try {
      const created = await create(apiSession, trimmed, idempotencyKey);
      // Re-key the optimistic entry to the real server id.
      setFeed((prev) =>
        prev.map((entry) =>
          entry.key === idempotencyKey
            ? { key: created.id, event: created, savedFood: entry.savedFood }
            : entry,
        ),
      );
      // We just reached the server — flush any earlier offline backlog now.
      drainNow();
    } catch (error) {
      if (isUnreachableError(error)) {
        // The server was unreachable: never a dead-end. Drop the transient
        // online-optimistic row and enqueue the raw capture into the durable
        // outbox — it re-renders as a calm offline-pending row, uncounted.
        setFeed((prev) => prev.filter((entry) => entry.key !== idempotencyKey));
        await enqueue(
          createOutboxEntry({
            idempotencyKey,
            userId: apiSession.userId,
            rawText: trimmed,
            capturedAt,
          }),
        );
      } else {
        // The server answered with an error — surface it and restore the
        // composer (including the saved-food association) so retry is one tap.
        setFeed((prev) => prev.filter((entry) => entry.key !== idempotencyKey));
        setText(trimmed);
        setSelectedSavedFood(pendingSavedFood);
        setSubmitError(messageFor(error));
      }
    } finally {
      setSubmitting(false);
    }
  }, [
    text,
    apiSession,
    submitting,
    create,
    selectedSavedFood,
    generateKey,
    now,
    enqueue,
    drainNow,
  ]);

  const handleBarcodeScanned = useCallback(
    async (barcode: string) => {
      setScannerOpen(false);
      if (!apiSession || submitting) return;

      const tempKey = `${OPTIMISTIC_ID_PREFIX}${tempId.current++}`;
      const optimistic = optimisticLogEvent({
        id: tempKey,
        userId: apiSession.userId,
        rawText: barcode,
        createdAt: new Date().toISOString(),
      });

      setFeed((prev) => [{ key: tempKey, event: optimistic, savedFood: null }, ...prev]);
      setSubmitting(true);
      setSubmitError(null);

      try {
        const created = await create(apiSession, barcode);
        setFeed((prev) =>
          prev.map((entry) =>
            entry.key === tempKey
              ? { key: created.id, event: created, savedFood: null }
              : entry,
          ),
        );
      } catch (error) {
        setFeed((prev) => prev.filter((entry) => entry.key !== tempKey));
        setSubmitError(messageFor(error));
      } finally {
        setSubmitting(false);
      }
    },
    [apiSession, submitting, create],
  );

  // Label upload returns the created event directly from the backend; add it to
  // the feed and let polling reconcile any later status change.
  const handleLabelUploaded = useCallback((event: LogEventDTO) => {
    setLabelCaptureOpen(false);
    setFeed((prev) => [{ key: event.id, event, savedFood: null }, ...prev]);
  }, []);

  const canSubmit = text.trim() !== "" && !submitting;

  if (!session) {
    return (
      <View
        style={[
          styles.center,
          { paddingTop: insets.top + 24, backgroundColor: colors.surface },
        ]}
      >
        <Text
          style={[styles.centerTitle, { color: colors.text }]}
          accessibilityRole="header"
        >
          Sign in to log food
        </Text>
        <Text style={[styles.centerBody, { color: colors.textMuted }]}>
          Your log is stored privately against your account. Sign in to start
          logging.
        </Text>
      </View>
    );
  }

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
            upload={(imageUri, savePhoto) =>
              uploadLabel(apiSession, imageUri, savePhoto)
            }
            takePhoto={labelTakePhoto}
          />
        )}
      </Modal>

      <ScrollView
        style={[styles.screen, { backgroundColor: colors.surface }]}
        contentContainerStyle={[
          styles.content,
          { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 96 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        {/* Calm connection-status banner (hidden when online and caught up). */}
        <ConnectionBanner state={reachability} queuedCount={queuedCount} />

        {/* Composer: keyboard-up natural-language input */}
        <View style={styles.composer}>
          <TextInput
            accessibilityLabel="Log food or exercise"
            placeholder="What did you eat or do?"
            placeholderTextColor={colors.textMuted}
            value={text}
            onChangeText={setText}
            multiline
            maxLength={MAX_RAW_TEXT_LENGTH}
            editable={!submitting}
            autoFocus
            style={[
              styles.input,
              { backgroundColor: colors.surfaceRaised, color: colors.text },
            ]}
          />
          <View style={styles.composerActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Scan barcode"
              accessibilityHint="Opens the camera to scan a product barcode"
              accessibilityState={{ disabled: submitting }}
              disabled={submitting}
              onPress={() => setScannerOpen(true)}
              style={[
                styles.captureButton,
                { backgroundColor: colors.controlBackground },
              ]}
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
              style={[
                styles.captureButton,
                { backgroundColor: colors.controlBackground },
              ]}
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
                styles.addButton,
                {
                  backgroundColor: canSubmit
                    ? colors.accent
                    : colors.controlBackground,
                },
              ]}
            >
              <Text
                style={[
                  styles.addButtonLabel,
                  {
                    color: canSubmit
                      ? colors.accentForeground
                      : colors.textMuted,
                  },
                ]}
              >
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
          <Text
            style={[styles.error, { color: colors.coral }]}
            accessibilityRole="alert"
          >
            {submitError}
          </Text>
        ) : null}

        {rows.length > 0 && (
          <View style={styles.feedSection}>
            <Text style={[styles.feedLabel, { color: colors.textMuted }]}>
              Added this session
            </Text>
            <View
              style={[
                styles.feedList,
                { backgroundColor: colors.surfaceRaised },
              ]}
            >
              {rows.map((entry, index) => (
                <View key={entry.key}>
                  {index > 0 && (
                    <View
                      style={[
                        styles.separator,
                        { backgroundColor: colors.separator },
                      ]}
                    />
                  )}
                  <FeedRow entry={entry} />
                </View>
              ))}
            </View>
          </View>
        )}
      </ScrollView>
    </>
  );
}

/**
 * A single row in the transient feed. While the entry is pending (and no
 * saved-food nutrition is immediately available), a skeleton/shimmer placeholder
 * fills the row. When the status reaches a terminal value — or immediately for a
 * saved-food entry — the resolved content fades in in the same slot.
 *
 * The container is always `FEED_ROW_HEIGHT` tall so the layout never shifts.
 */
function FeedRow({ entry }: { entry: FeedEntry }) {
  const { colors } = useTheme();

  // An offline-queued capture is not on the server yet — it renders as a calm,
  // uncounted offline-pending row (raw text + an explicit offline indicator),
  // never a shimmer (it is not being estimated) and never a fabricated number.
  if (entry.offline) {
    return <OfflineFeedRow entry={entry} />;
  }

  // A saved-food entry has nutrition immediately; skip the skeleton for it.
  const showResolved =
    entry.savedFood != null || !isNonTerminal(entry.event.status);

  const displayName = entry.savedFood?.name ?? entry.event.raw_text;
  const calories = entry.savedFood?.calories ?? null;

  // A saved-food entry carries resolved nutrition immediately, so it reads as
  // logged; an estimator-driven entry takes its status from the exhaustive
  // presentation map so failed / needs_clarification never read as "logged".
  const { accessibilityLabel: statusLabel } = statusPresentation(
    entry.savedFood != null ? "completed" : entry.event.status,
  );

  const pendingLabel = `${displayName}, estimating`;
  const resolvedLabel =
    calories != null
      ? `${displayName}, ${calories} kcal, ${statusLabel}`
      : `${displayName}, ${statusLabel}`;

  return (
    <View
      style={[styles.feedRow, { backgroundColor: colors.surfaceRaised }]}
      accessible
      accessibilityLabel={showResolved ? resolvedLabel : pendingLabel}
    >
      {!showResolved && <Skeleton width="100%" height={FEED_ROW_HEIGHT} />}
      {showResolved && <FeedRowResolved entry={entry} />}
    </View>
  );
}

/**
 * Calm presentation for the offline indicator, by local sync state. The state is
 * always carried in words (never colour alone), and no kcal/macro value is ever
 * shown — an offline-queued entry is uncounted until the server resolves it.
 */
function offlineIndicator(state: OutboxSyncState): {
  readonly glyph: string;
  readonly label: string;
  readonly a11y: string;
} {
  switch (state) {
    case "submitting":
      return { glyph: "⟳", label: "Sending…", a11y: "sending" };
    case "failed":
      return {
        glyph: "!",
        label: "Couldn't send",
        a11y: "couldn't send",
      };
    case "queued":
    case "accepted":
    default:
      return {
        glyph: "⇡",
        label: "Offline — queued",
        a11y: "offline, queued to send",
      };
  }
}

/**
 * A single offline-queued row. It shows the raw captured text and an explicit,
 * accessible offline indicator, at the same fixed height as every other feed row
 * so the layout never shifts when the entry later resolves online.
 */
function OfflineFeedRow({ entry }: { entry: FeedEntry }) {
  const { colors } = useTheme();
  const indicator = offlineIndicator(entry.offline ?? "queued");
  const displayName = entry.event.raw_text;

  return (
    <View
      style={[styles.feedRow, { backgroundColor: colors.surfaceRaised }]}
      accessible
      accessibilityLabel={`${displayName}, ${indicator.a11y}`}
    >
      <View style={styles.feedRowContent}>
        <Text
          style={[styles.feedRowName, { color: colors.text }]}
          numberOfLines={1}
        >
          {displayName}
        </Text>
        <View style={styles.offlineIndicator}>
          <Text style={[styles.offlineGlyph, { color: colors.textMuted }]}>
            {indicator.glyph}
          </Text>
          <Text
            style={[styles.feedRowMeta, { color: colors.textMuted }]}
            numberOfLines={1}
          >
            {indicator.label}
          </Text>
        </View>
      </View>
    </View>
  );
}

/** The resolved content of a feed row, fading in on mount. */
function FeedRowResolved({ entry }: { entry: FeedEntry }) {
  const { colors } = useTheme();
  // Animated.Value is a stable mutable handle stored in a ref per the RN
  // Animated API contract (same pattern as Skeleton); reading `.current` here
  // is intentional and safe, so the react-hooks/refs rule is suppressed.
  // eslint-disable-next-line react-hooks/refs
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((reduceMotion) => {
      if (!mounted) return;
      if (reduceMotion) {
        Animated.timing(opacity, {
          toValue: 1,
          duration: reducedMotionDuration,
          useNativeDriver: true,
        }).start();
      } else {
        Animated.spring(opacity, {
          ...gentleSpring,
          toValue: 1,
        }).start();
      }
    });
    return () => {
      mounted = false;
    };
  }, [opacity]);

  const displayName = entry.savedFood?.name ?? entry.event.raw_text;
  const calories = entry.savedFood?.calories ?? null;
  // Terminal status copy from the exhaustive map — completed -> "Logged",
  // failed -> "Couldn't estimate", needs_clarification -> "Add a detail".
  const statusLabel = statusPresentation(
    entry.savedFood != null ? "completed" : entry.event.status,
  ).label;

  return (
    <Animated.View style={[styles.feedRowContent, { opacity }]}>
      <Text
        style={[styles.feedRowName, { color: colors.text }]}
        numberOfLines={1}
      >
        {displayName}
      </Text>
      {calories != null ? (
        <Text
          style={[styles.feedRowMeta, { color: colors.textSecondary }]}
          numberOfLines={1}
        >
          {calories} kcal
        </Text>
      ) : (
        <Text
          style={[styles.feedRowMeta, { color: colors.textMuted }]}
          numberOfLines={1}
        >
          {statusLabel}
        </Text>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
  },
  content: {
    paddingHorizontal: spacing.base,
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
  captureButton: {
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
  addButton: {
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  addButtonLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  error: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.md,
    marginLeft: spacing.xs,
  },
  feedSection: {
    marginTop: spacing.base,
  },
  feedLabel: {
    fontSize: typeScale.caption1,
    fontWeight: "500",
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  feedList: {
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  feedRow: {
    height: FEED_ROW_HEIGHT,
    overflow: "hidden",
    justifyContent: "center",
  },
  feedRowContent: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.sm,
    justifyContent: "center",
    gap: 2,
  },
  feedRowName: {
    fontSize: typeScale.subhead,
    fontWeight: "500",
  },
  feedRowMeta: {
    fontSize: typeScale.footnote,
  },
  offlineIndicator: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  offlineGlyph: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    marginLeft: spacing.base,
  },
  center: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
  },
  centerTitle: {
    fontSize: typeScale.title2,
    fontWeight: "700",
    textAlign: "center",
  },
  centerBody: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    marginTop: spacing.md,
  },
});
