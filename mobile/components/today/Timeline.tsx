import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { type LogEventDTO } from "@/api/logEvents";
import { type OutboxSyncState } from "@/state/outbox";
import { clusterByTime } from "@/state/today";
import { useTheme, spacing, typeScale, radius } from "@/theme";

import { ClusterView } from "./ClusterView";
import { type Phase } from "./helpers";

/**
 * The Today timeline body: the loading / empty / error states and the
 * newest-first clustered entry cards. Kept a pure view block — the screen shell
 * owns the data/poll state and hands it the reconciled events, items, and
 * per-row callbacks.
 */
export function Timeline({
  events,
  itemsByEvent,
  offlineStateById,
  resolveAnimIds,
  onOpenItem,
  onOpenProposal,
  onOpenClarify,
  onRetryFailed,
  onEditFailedAsText,
  phase,
  loadError,
  onRetry,
}: {
  events: readonly LogEventDTO[];
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  /** Idempotency key → offline sync state for offline-queued rows (FTY-147). */
  offlineStateById: ReadonlyMap<string, OutboxSyncState>;
  /** Event ids whose value row should ease in — the entry-resolve beat (FTY-181). */
  resolveAnimIds: ReadonlySet<string>;
  onOpenItem: (item: DerivedItem, logPhrase: string) => void;
  /** Reopen the confirm sheet for an uncounted label proposal (FTY-197). */
  onOpenProposal: (item: DerivedFoodItemDTO) => void;
  onOpenClarify: (event: LogEventDTO) => void;
  /** Retry a failed parse as a fresh attempt (FTY-176). */
  onRetryFailed: (event: LogEventDTO) => void;
  /** Prefill the composer with a failed entry's text to fix + resubmit (FTY-176). */
  onEditFailedAsText: (event: LogEventDTO) => void;
  phase: Phase;
  loadError: string | null;
  onRetry: () => void;
}) {
  const { colors } = useTheme();

  if (events.length === 0) {
    if (phase === "loading") {
      return (
        <View style={styles.state}>
          <ActivityIndicator accessibilityLabel="Loading your day" />
        </View>
      );
    }
    // An empty day still shows the hero (zeroed intake, full target available)
    // and a calm single invite — never an alarming blank.
    return (
      <View>
        {phase === "error" ? (
          <View style={styles.state}>
            <Text
              style={[styles.stateText, { color: colors.textSecondary }]}
              accessibilityRole="alert"
            >
              {loadError}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Try again"
              onPress={onRetry}
              style={styles.retry}
            >
              <Text style={[styles.retryLabel, { color: colors.text }]}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.state} testID="today-timeline-ready">
            <Text style={[styles.stateText, { color: colors.textMuted }]}>
              Log your first thing
            </Text>
          </View>
        )}
      </View>
    );
  }

  const clusters = clusterByTime(events);

  return (
    <View testID="today-timeline-with-entries">
      {phase === "error" && loadError ? (
        <Text
          style={[styles.error, { color: colors.textSecondary }]}
          accessibilityRole="alert"
        >
          {loadError}
        </Text>
      ) : null}

      {clusters.map((cluster) => (
        <ClusterView
          key={cluster.anchorTime}
          cluster={cluster}
          itemsByEvent={itemsByEvent}
          offlineStateById={offlineStateById}
          resolveAnimIds={resolveAnimIds}
          onOpenItem={onOpenItem}
          onOpenProposal={onOpenProposal}
          onOpenClarify={onOpenClarify}
          onRetryFailed={onRetryFailed}
          onEditFailedAsText={onEditFailedAsText}
          colors={colors}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  error: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.md,
    marginLeft: spacing.xs,
  },
  state: {
    paddingVertical: 32,
    alignItems: "center",
    gap: spacing.base,
  },
  stateText: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    paddingHorizontal: spacing.base,
  },
  retry: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: radius.md,
  },
  retryLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "600",
  },
});
