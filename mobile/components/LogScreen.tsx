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
import { LabelCaptureScreen } from "@/components/LabelCaptureScreen";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import { Skeleton } from "@/components/ui";
import {
  POLL_INTERVAL_MS,
  hasPendingWork,
  isNonTerminal,
  useIntervalPolling,
} from "@/state/polling";
import {
  OPTIMISTIC_ID_PREFIX,
  optimisticLogEvent,
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

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || !apiSession || submitting) return;

    const tempKey = `${OPTIMISTIC_ID_PREFIX}${tempId.current++}`;
    const pendingSavedFood = selectedSavedFood;
    setSelectedSavedFood(null);

    const optimistic = optimisticLogEvent({
      id: tempKey,
      userId: apiSession.userId,
      rawText: trimmed,
      createdAt: new Date().toISOString(),
    });

    setFeed((prev) => [{ key: tempKey, event: optimistic, savedFood: pendingSavedFood }, ...prev]);
    // Clear the composer immediately so the next entry can be typed at once.
    setText("");
    setSubmitting(true);
    setSubmitError(null);

    try {
      const created = await create(apiSession, trimmed);
      // Re-key the optimistic entry to the real server id.
      setFeed((prev) =>
        prev.map((entry) =>
          entry.key === tempKey
            ? { key: created.id, event: created, savedFood: entry.savedFood }
            : entry,
        ),
      );
    } catch (error) {
      setFeed((prev) => prev.filter((entry) => entry.key !== tempKey));
      setText(trimmed);
      setSubmitError(messageFor(error));
    } finally {
      setSubmitting(false);
    }
  }, [text, apiSession, submitting, create, selectedSavedFood]);

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
              <Text style={[styles.captureButtonLabel, { color: colors.text }]}>
                ⊡
              </Text>
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
              <Text style={[styles.captureButtonLabel, { color: colors.text }]}>
                ◉
              </Text>
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

        {feed.length > 0 && (
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
              {feed.map((entry, index) => (
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

  // A saved-food entry has nutrition immediately; skip the skeleton for it.
  const showResolved =
    entry.savedFood != null || !isNonTerminal(entry.event.status);

  const displayName = entry.savedFood?.name ?? entry.event.raw_text;
  const calories = entry.savedFood?.calories ?? null;

  const pendingLabel = `${displayName}, estimating`;
  const resolvedLabel =
    calories != null
      ? `${displayName}, ${calories} kcal, logged`
      : `${displayName}, logged`;

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

/** The resolved content of a feed row, fading in on mount. */
function FeedRowResolved({ entry }: { entry: FeedEntry }) {
  const { colors } = useTheme();
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
          {entry.event.status === "completed" ? "Logged" : "Estimating…"}
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
    flexDirection: "column",
    gap: 6,
    alignItems: "center",
  },
  captureButton: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  captureButtonLabel: {
    fontSize: 22,
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
