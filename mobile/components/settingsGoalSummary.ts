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
 * Direction is the authoritative, always-known part of a loaded goal
 * (`GET /goal`, FTY-189), so it is what the row summarises. Pace is only known
 * once a goal is created or edited this session — it is never persisted back to
 * the client and is never guessed or reverse-engineered from target numbers.
 * When pace is unknown the row still summarises the real goal by its direction
 * (`Lose`) rather than collapsing to a dead `Details unavailable`; when pace is
 * known it is appended (`Lose · Steady`). Maintain goals have no pace and read
 * as `Maintain`. Only a genuinely unknown direction (no active goal loaded)
 * stays neutral.
 */
export function goalSummaryDetail(
  direction: GoalDirection | null,
  pace: PacePreset | null | undefined,
): string {
  if (direction === null) return 'Details unavailable';
  if (direction === 'maintain' || !pace) return DIRECTION_LABELS[direction];
  return `${DIRECTION_LABELS[direction]} · ${PACE_LABELS[pace]}`;
}
