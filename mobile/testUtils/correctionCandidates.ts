/**
 * Builder for the `source-candidates` response the correction sheet consumes
 * (FTY-093 guessed sources + FTY-411 prior corrections).
 *
 * `listSourceCandidates` returns both lists in one structured result, so a test
 * stubbing it has to supply both. This keeps that shape in one place: a suite
 * that only cares about the guessed candidates writes `sourceCandidates([c])`
 * and gets an empty prior-correction list — the "no matching history" default,
 * which is exactly the pre-FTY-407 behaviour those suites assert.
 */

import type {
  PriorCorrectionCandidate,
  SourceCandidate,
  SourceCandidates,
} from "@/api/corrections";

export function sourceCandidates(
  candidates: readonly SourceCandidate[] = [],
  priorCorrections: readonly PriorCorrectionCandidate[] = [],
): SourceCandidates {
  return { candidates, priorCorrections };
}
