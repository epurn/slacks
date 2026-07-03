/**
 * Shared visual styles for the goal-led onboarding flow (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206) so the wizard shell, the
 * step sections, and the form primitives all draw on one cohesive style sheet
 * rather than duplicating token-based rules. Everything is built on FTY-097
 * design tokens.
 */

import { StyleSheet } from 'react-native';

import { radius, spacing, typeScale } from '@/theme';

export const styles = StyleSheet.create({
  stepContainer: {
    flex: 1,
    paddingTop: spacing.xl,
  },
  stepperRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  backButton: {
    minHeight: 44,
    minWidth: 60,
    justifyContent: 'center',
  },
  backButtonLabel: {
    fontSize: typeScale.body,
    fontWeight: '500',
  },
  backButtonPlaceholder: {
    minWidth: 60,
  },
  dotsContainer: {
    flexDirection: 'row',
    gap: spacing.xs,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: {
    height: 8,
    borderRadius: radius.full,
  },
  stepTitle: {
    fontSize: typeScale.largeTitle,
    fontWeight: '700',
    letterSpacing: -0.5,
    marginBottom: spacing.sm,
  },
  stepSubtitle: {
    fontSize: typeScale.body,
    marginBottom: spacing.xl,
    lineHeight: 22,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: spacing.lg,
    marginBottom: spacing.xs,
  },
  segmented: {
    flexDirection: 'row',
    borderRadius: radius.md,
    padding: 2,
    gap: 2,
  },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    alignItems: 'center',
    minHeight: 44,
    justifyContent: 'center',
  },
  segmentLabel: {
    fontSize: typeScale.footnote,
  },
  paceNote: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  autoDetectRow: {
    padding: spacing.md,
    marginBottom: spacing.lg,
    gap: spacing.xs,
  },
  autoDetectLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '500',
  },
  autoDetectNote: {
    fontSize: typeScale.caption1,
    marginTop: spacing.xs,
  },
  fieldGroup: {
    marginTop: spacing.md,
  },
  fieldLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  textInput: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: typeScale.body,
    minHeight: 44,
  },
  fieldError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.xs,
  },
  imperialHeightRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  imperialHeightInput: {
    flex: 1,
  },
  formulaNote: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  formulaChoice: {
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: spacing.md,
    marginBottom: spacing.xs,
    minHeight: 60,
    justifyContent: 'center',
  },
  formulaChoiceLabel: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
  },
  formulaChoiceDesc: {
    fontSize: typeScale.footnote,
    marginTop: 2,
  },
  saveError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.md,
    textAlign: 'center',
  },
  primaryAction: {
    marginTop: spacing.xxl,
  },
  // Step 3 — Target reveal
  heroContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xxxl,
  },
  heroNumber: {
    fontSize: typeScale.heroDisplay,
    fontWeight: '700',
    letterSpacing: -1,
    fontVariant: ['tabular-nums'],
  },
  heroUnit: {
    fontSize: typeScale.title3,
    marginTop: spacing.xs,
  },
  provenanceLine: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
  },
  clampCard: {
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  clampTitle: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  clampBody: {
    fontSize: typeScale.footnote,
    lineHeight: 18,
  },
  revealNote: {
    fontSize: typeScale.footnote,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
});
