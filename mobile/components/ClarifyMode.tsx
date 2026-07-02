import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { useTheme, spacing, typeScale, radius } from "@/theme";

/** Clarification data for an item in the needs_clarification state. */
export interface ClarificationData {
  /**
   * Fatty's specific question (e.g. "What kind of milk?"), or `null` while the
   * clarification read is loading or when the event has no persisted question.
   * Clarify-mode falls back to the generic prompt + free-text when it is `null`.
   */
  readonly question: string | null;
  /**
   * Quick-pick answer options (tappable chips), from the clarification payload
   * (FTY-170). MAY be empty — deterministic backend-raised questions carry none,
   * and the read is still loading — in which case the sheet shows the free-text
   * affordance only. Never synthesized client-side.
   */
  readonly options: readonly string[];
}

export function ClarifyMode({
  clarificationData,
  clarifyText,
  onChangeClarifyText,
  onSubmitAnswer,
  submitting,
  colors,
  logPhrase,
}: {
  clarificationData?: ClarificationData;
  clarifyText: string;
  onChangeClarifyText: (v: string) => void;
  onSubmitAnswer: (answer: string) => void;
  submitting: boolean;
  colors: ReturnType<typeof useTheme>["colors"];
  logPhrase?: string;
}) {
  return (
    <View style={styles.clarifySection}>
      {logPhrase ? (
        <View style={styles.clarifyPhraseBlock}>
          <Text style={[styles.clarifyPhraseLabel, { color: colors.textMuted }]}>
            Logged phrase
          </Text>
          <Text
            testID="clarify-full-phrase"
            style={[styles.clarifyPhrase, { color: colors.text }]}
            accessibilityLabel={`Logged phrase: ${logPhrase}`}
          >
            {logPhrase}
          </Text>
        </View>
      ) : null}

      <Text
        testID="clarify-question"
        style={[styles.clarifyQuestion, { color: colors.text }]}
      >
        {clarificationData?.question ?? "We need a detail to count this entry."}
      </Text>

      {clarificationData && clarificationData.options.length > 0 ? (
        <View style={styles.chipRow} accessibilityRole="radiogroup">
          {clarificationData.options.map((option) => (
            <Pressable
              key={option}
              onPress={() => onSubmitAnswer(option)}
              style={[styles.chip, { backgroundColor: colors.controlBackground }]}
              accessibilityRole="radio"
              accessibilityLabel={option}
              disabled={submitting}
              accessibilityState={{ disabled: submitting }}
            >
              <Text style={[styles.chipLabel, { color: colors.text }]}>{option}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      <Text style={[styles.clarifyOrLabel, { color: colors.textMuted }]}>
        {clarificationData && clarificationData.options.length > 0
          ? "Or type your own:"
          : "Type your answer:"}
      </Text>
      <View style={styles.clarifyInputRow}>
        <TextInput
          accessibilityLabel="Your answer"
          placeholder="Type your answer…"
          placeholderTextColor={colors.textMuted}
          value={clarifyText}
          onChangeText={onChangeClarifyText}
          style={[
            styles.clarifyInput,
            {
              backgroundColor: colors.controlBackground,
              color: colors.text,
              flex: 1,
            },
          ]}
          editable={!submitting}
          returnKeyType="done"
          onSubmitEditing={() => {
            if (clarifyText.trim()) {
              onSubmitAnswer(clarifyText);
            }
          }}
        />
        <Pressable
          onPress={() => {
            if (clarifyText.trim()) {
              onSubmitAnswer(clarifyText);
            }
          }}
          style={[
            styles.clarifySubmitBtn,
            { backgroundColor: clarifyText.trim() ? colors.accent : colors.controlBackground },
          ]}
          accessibilityRole="button"
          accessibilityLabel="Submit answer"
          disabled={submitting || !clarifyText.trim()}
          accessibilityState={{ disabled: submitting || !clarifyText.trim() }}
        >
          <Text
            style={[
              styles.clarifySubmitLabel,
              { color: clarifyText.trim() ? colors.accentForeground : colors.textMuted },
            ]}
          >
            {submitting ? "…" : "Done"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  clarifySection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.lg,
    gap: spacing.md,
  },
  clarifyPhraseBlock: {
    gap: spacing.xs,
  },
  clarifyPhraseLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  clarifyPhrase: {
    fontSize: typeScale.callout,
    lineHeight: 22,
  },
  clarifyQuestion: {
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  chip: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    minHeight: 44,
    justifyContent: "center",
  },
  chipLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  clarifyOrLabel: {
    fontSize: typeScale.footnote,
  },
  clarifyInputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  clarifyInput: {
    height: 44,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  clarifySubmitBtn: {
    width: 60,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  clarifySubmitLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
});
