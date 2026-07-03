import type { GoalDirection, PacePreset } from '@/api/goals';

const PACE_LABELS: Record<PacePreset, string> = {
  gentle: 'Gentle',
  steady: 'Steady',
  faster: 'Faster',
};

const DIRECTION_LABELS: Record<GoalDirection, string> = {
  loss: 'Lose',
  maintain: 'Maintain',
  gain: 'Gain',
};

/**
 * Collapsed Goal-row summary for the caller's active goal.
 *
 * Direction is recovered from the real goal on a cold load (`GET /goal`, the
 * FTY-189 direction read model) so the row shows the real goal — never the dead
 * "Active" state. Pace is known only from the user's own goal edit this session;
 * it is never guessed or reverse-engineered from target numbers, and never
 * persisted on-device. A directional goal with a known pace summarises as
 * direction + pace (`Lose · Steady`); before an in-session edit it summarises by
 * its direction alone (`Lose`). Maintain goals have no pace and read as
 * `Maintain`. Only a genuinely unknown direction (no active goal loaded) stays
 * neutral (`Details unavailable`).
 */
export function goalSummaryDetail(
  direction: GoalDirection | null,
  pace: PacePreset | null | undefined,
): string {
  if (direction === null) return 'Details unavailable';
  if (direction === 'maintain' || !pace) return DIRECTION_LABELS[direction];
  return `${DIRECTION_LABELS[direction]} · ${PACE_LABELS[pace]}`;
}
