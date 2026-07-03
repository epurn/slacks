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
 * Both direction and pace are recovered from the real goal on a cold load
 * (`GET /goal`, FTY-189/FTY-190) — pace is the exact inverse of the band the
 * persisted trajectory was derived from, never guessed or reverse-engineered from
 * target numbers, and never persisted on-device. A directional goal summarises as
 * direction + pace (`Lose · Steady`). Maintain goals have no pace and read as
 * `Maintain`. When pace is genuinely absent (a legacy goal off the band grid) the
 * row still summarises the real goal by its direction alone (`Lose`) rather than
 * collapsing to a dead `Details unavailable` or inventing a pace. Only a genuinely
 * unknown direction (no active goal loaded) stays neutral.
 */
export function goalSummaryDetail(
  direction: GoalDirection | null,
  pace: PacePreset | null | undefined,
): string {
  if (direction === null) return 'Details unavailable';
  if (direction === 'maintain' || !pace) return DIRECTION_LABELS[direction];
  return `${DIRECTION_LABELS[direction]} · ${PACE_LABELS[pace]}`;
}
