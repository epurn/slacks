/**
 * FTY-204: Change-match panel — alternative source search + re-resolve (FTY-093).
 *
 * A debounced search field over the candidate list, with skeleton / error /
 * empty states and a re-resolve error banner. Extracted from the former
 * monolithic `CorrectionSheet.tsx` — behaviour, copy, and accessibility labels
 * are unchanged (the internal typo'd `ChangMatch*` names are corrected here).
 */

import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type { SourceCandidate } from "@/api/corrections";
import { Skeleton } from "@/components/ui/Skeleton";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

export function ChangeMatchPanel({
  query,
  onQueryChange,
  candidates,
  loading,
  error,
  reResolving,
  reResolveError,
  onPickCandidate,
  onCancel,
  colors,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  candidates: readonly SourceCandidate[];
  loading: boolean;
  error: string | null;
  reResolving: boolean;
  reResolveError: string | null;
  onPickCandidate: (c: SourceCandidate) => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.changeMatchPanel}>
      <View style={styles.changeMatchHeader}>
        <Text style={[styles.changeMatchTitle, { color: colors.text }]}>
          Change match
        </Text>
        <Pressable
          onPress={onCancel}
          accessibilityLabel="Cancel change match"
          accessibilityRole="button"
          style={styles.cancelButton}
        >
          <Text style={[styles.cancelLabel, { color: colors.accentText }]}>Cancel</Text>
        </Pressable>
      </View>

      {/* Search field */}
      <TextInput
        accessibilityLabel="Search for a food"
        placeholder="Search for a different food…"
        placeholderTextColor={colors.textMuted}
        value={query}
        onChangeText={onQueryChange}
        style={[
          styles.searchInput,
          {
            backgroundColor: colors.controlBackground,
            color: colors.text,
          },
        ]}
        returnKeyType="search"
        autoCorrect={false}
        clearButtonMode="while-editing"
      />

      {reResolveError ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {reResolveError}
        </Text>
      ) : null}

      {loading ? (
        <View style={styles.candidateSkeletonList}>
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
        </View>
      ) : error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : candidates.length === 0 ? (
        <Text style={[styles.emptyLabel, { color: colors.textMuted }]}>
          {query.trim() ? "No matches found. Try a different search." : "No alternatives available."}
        </Text>
      ) : (
        <View style={styles.candidateList} accessibilityRole="list">
          {candidates.map((candidate) => (
            <Pressable
              key={candidate.source_ref}
              onPress={() => onPickCandidate(candidate)}
              style={({ pressed }) => [
                styles.candidateRow,
                { borderBottomColor: colors.separator },
                pressed && { opacity: 0.7 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={`Select ${candidate.name}, ${Math.round(candidate.calories)} kcal per 100g`}
              disabled={reResolving}
              accessibilityState={{ disabled: reResolving }}
            >
              <View style={styles.candidateInfo}>
                <Text style={[styles.candidateName, { color: colors.text }]} numberOfLines={1}>
                  {candidate.name}
                </Text>
                <Text style={[styles.candidateMeta, { color: colors.textMuted }]}>
                  {Math.round(candidate.calories)} kcal / 100g
                </Text>
              </View>
              {reResolving ? null : (
                <Text style={[styles.candidateChevron, { color: colors.textMuted }]}>›</Text>
              )}
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  changeMatchPanel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  changeMatchHeader: {
    flexDirection: "row",
    alignItems: "center",
  },
  changeMatchTitle: {
    flex: 1,
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  cancelButton: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  cancelLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  searchInput: {
    height: 44,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  candidateSkeletonList: {
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  candidateList: {
    marginTop: spacing.xs,
  },
  candidateRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 56,
    gap: spacing.sm,
  },
  candidateInfo: {
    flex: 1,
    gap: 2,
  },
  candidateName: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  candidateMeta: {
    fontSize: typeScale.footnote,
    fontVariant: ["tabular-nums"],
  },
  candidateChevron: {
    fontSize: typeScale.title3,
  },
  emptyLabel: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
