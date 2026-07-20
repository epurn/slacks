/**
 * FTY-204: Change-match panel — alternative source search + re-resolve (FTY-093).
 *
 * A debounced search field over the candidate list, with skeleton / error /
 * empty states and a re-resolve error banner. Extracted from the former
 * monolithic `CorrectionSheet.tsx` — behaviour, copy, and accessibility labels
 * are unchanged (the internal typo'd `ChangMatch*` names are corrected here).
 *
 * FTY-407: the user's own prior corrections for this item's name (`priorCorrections`,
 * from FTY-411) render as a top-ranked "Your corrections" group **above** the
 * guessed-source matches, so re-teaching a food they've already corrected is a
 * one-tap pick. When there are none, the panel renders exactly as before.
 */

import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type {
  PickableCandidate,
  PriorCorrectionCandidate,
  SourceCandidate,
} from "@/api/corrections";
import { AppIcon } from "@/components/ui/AppIcon";
import { DisplayText } from "@/components/ui/DisplayText";
import { Skeleton } from "@/components/ui/Skeleton";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

/** Leading provenance-slot width, shared by the icon and the guessed-row spacer. */
const ICON_SIZE = 16;

export function ChangeMatchPanel({
  query,
  onQueryChange,
  candidates,
  priorCorrections,
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
  priorCorrections: readonly PriorCorrectionCandidate[];
  loading: boolean;
  error: string | null;
  reResolving: boolean;
  reResolveError: string | null;
  onPickCandidate: (c: PickableCandidate) => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  const hasPriorCorrections = priorCorrections.length > 0;
  const hasCandidates = candidates.length > 0;
  return (
    <View style={styles.changeMatchPanel}>
      <View style={styles.changeMatchHeader}>
        <DisplayText scale="headline" style={styles.changeMatchTitle}>
          Change match
        </DisplayText>
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
      ) : !hasCandidates && !hasPriorCorrections ? (
        <Text style={[styles.emptyLabel, { color: colors.textMuted }]}>
          {query.trim() ? "No matches found. Try a different search." : "No alternatives available."}
        </Text>
      ) : (
        <View>
          {/* FTY-407: the user's own corrections, ranked above every guessed
              source (mirroring the FTY-406 estimate-time tier order). */}
          {hasPriorCorrections ? (
            <>
              <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
                Your corrections
              </Text>
              <View style={styles.candidateList} accessibilityRole="list">
                {priorCorrections.map((correction) => (
                  <Pressable
                    key={correction.source_ref}
                    onPress={() => onPickCandidate(correction)}
                    style={({ pressed }) => [
                      styles.candidateRow,
                      { borderBottomColor: colors.separator },
                      pressed && { opacity: 0.7 },
                    ]}
                    accessibilityRole="button"
                    accessibilityLabel={priorCorrectionLabel(correction)}
                    disabled={reResolving}
                    accessibilityState={{ disabled: reResolving }}
                  >
                    {/* Provenance, always on: this value is the user's own. The
                        fixed-width slot is what the guessed rows below mirror
                        with a spacer, so both groups' text starts on one grid. */}
                    <View style={styles.candidateLeading}>
                      <AppIcon name="pencil" size={ICON_SIZE} color={colors.textMuted} />
                    </View>
                    <View style={styles.candidateInfo}>
                      <Text
                        style={[styles.candidateName, { color: colors.text }]}
                        numberOfLines={1}
                      >
                        {correction.name}
                      </Text>
                      <Text style={[styles.candidateMeta, { color: colors.textMuted }]}>
                        {priorCorrectionMeta(correction)}
                      </Text>
                    </View>
                    {reResolving ? null : (
                      <Text style={[styles.candidateChevron, { color: colors.textMuted }]}>›</Text>
                    )}
                  </Pressable>
                ))}
              </View>
            </>
          ) : null}

          {/* The guessed-source matches. Unchanged when there is no history —
              no header, same rows — so the no-history path is a no-op. */}
          {hasCandidates ? (
            <>
              {hasPriorCorrections ? (
                <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>
                  Other matches
                </Text>
              ) : null}
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
                    {/* Only when the grouped list is on screen: an empty slot the
                        width of the prior-correction rows' pencil, so both
                        groups' names/meta share one left edge. With no history
                        there is no group to align to and the row is unchanged. */}
                    {hasPriorCorrections ? (
                      <View style={styles.candidateLeading} />
                    ) : null}
                    <View style={styles.candidateInfo}>
                      <Text
                        style={[styles.candidateName, { color: colors.text }]}
                        numberOfLines={1}
                      >
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
            </>
          ) : null}
        </View>
      )}
    </View>
  );
}

/**
 * The visible meta line for a prior correction: the corrected **total** for this
 * item's own portion (`basis === "as_logged"` — never a per-100g density, which
 * is why this does not reuse the guessed-source "/ 100g" copy), plus its
 * provenance. A value carried from a differently-portioned prior says so.
 */
function priorCorrectionMeta(correction: PriorCorrectionCandidate): string {
  const kcal = `${Math.round(correction.calories)} kcal`;
  return correction.rescaled
    ? `${kcal} · Your correction, adjusted for this amount`
    : `${kcal} · Your correction`;
}

/**
 * VoiceOver label for a prior-correction row. Screen-reader users get the same
 * provenance signal as sighted users (the pencil icon + "Your correction"),
 * phrased as speech rather than the visible middot-separated meta line.
 */
function priorCorrectionLabel(correction: PriorCorrectionCandidate): string {
  const adjusted = correction.rescaled ? ", adjusted for this amount" : "";
  return `Select ${correction.name}, your correction, ${Math.round(correction.calories)} kcal${adjusted}`;
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
  // Grouped-list section header (FTY-407). Only rendered when there is history
  // to separate — a candidate list with no prior corrections is unchanged.
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    marginTop: spacing.md,
  },
  candidateRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 56,
    gap: spacing.sm,
  },
  // Fixed-width leading slot (FTY-407): the pencil on a prior-correction row, an
  // empty spacer on a guessed row, so a grouped list keeps one text grid.
  candidateLeading: {
    width: ICON_SIZE,
    alignItems: "center",
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
