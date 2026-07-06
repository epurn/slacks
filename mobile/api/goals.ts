/**
 * Typed clients for the FTY-106 goal endpoint and FTY-095 target
 * override/reset endpoints.
 *
 * Endpoints consumed:
 *   POST /api/users/{user_id}/goal               — create/replace active goal (FTY-106)
 *   GET  /api/users/{user_id}/target             — target read-model (FTY-095)
 *   PUT  /api/users/{user_id}/target/override    — set override (FTY-095)
 *   POST /api/users/{user_id}/target/override/reset — reset override (FTY-095)
 *
 * Privacy: calorie, macro, and body-metric values are sensitive derived body
 * data. Errors carry only the HTTP status and the action, never target numbers.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from '@/api/client';
import type { ApiSession } from '@/api/client';
import type { TargetReadModel } from '@/api/dailySummary';

/** Direction of a weight goal. */
export type GoalDirection = 'loss' | 'gain' | 'maintain';

/** Evidence-based pace preset for loss/gain goals. */
export type PacePreset = 'gentle' | 'steady' | 'faster';

/** One independently overridable target key. */
export type OverridableTargetKey = 'calories' | 'protein' | 'carbs' | 'fat';

/**
 * The caller's current active goal, summarised (`GET /goal`, FTY-189/FTY-190).
 *
 * The single authoritative source of a returning user's goal: neither the
 * daily-summary nor the target read-model carries direction or pace, and the
 * in-memory cross-screen seam only knows a goal created/edited *this* session.
 * Both fields are recovered server-side from the persisted trajectory — direction
 * from its sign, pace as the exact inverse of the band it was derived from — so a
 * cold launch reads the real goal. `pace` is `null` for a maintain goal or a
 * legacy goal off the band grid. Trends reads `direction` to colour the weight
 * delta by progress toward the goal; Settings reads both to summarise the Goal row
 * as direction + pace.
 */
export interface ActiveGoal {
  readonly direction: GoalDirection;
  readonly pace: PacePreset | null;
}

/** Persisted goal representation returned by the goal endpoint. */
interface GoalDTO {
  readonly id: string;
  readonly user_id: string;
  readonly start_weight_kg: number;
  readonly start_date: string;
  readonly target_weight_kg: number;
  readonly target_date: string;
  readonly is_active: boolean;
}

/** Revealed target info returned alongside the created goal (FTY-106). */
interface RevealedTarget {
  readonly calories: number;
  readonly rmr_kcal: number;
  readonly tdee_kcal: number;
  readonly direction: GoalDirection;
  readonly clamped: boolean;
}

/** Combined goal + target reveal returned by POST /goal (FTY-106). */
export interface GoalTargetResponse {
  readonly goal: GoalDTO;
  readonly target: RevealedTarget;
  readonly provenance: {
    readonly source: 'derived' | 'user';
    readonly basis: 'goal_and_metrics';
  };
  readonly clamp: {
    readonly clamped: boolean;
    readonly reason: string | null;
  };
}

/** Request body for creating/replacing the active goal. */
export interface GoalTargetRequest {
  /** lose / maintain / gain */
  readonly direction: GoalDirection;
  /** Required for loss/gain; ignored for maintain. */
  readonly pace?: PacePreset;
}

/** Payload for setting manual target overrides (FTY-095). */
export interface TargetOverridePayload {
  readonly calorie_target_kcal?: number;
  readonly protein_target_g?: number;
  readonly carbs_target_g?: number;
  readonly fat_target_g?: number;
}

/** Authenticated session needed to reach these endpoints. */
export type GoalsSession = ApiSession;

/** Raised when a goal or target endpoint returns a non-2xx status. */
export class GoalsApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = 'GoalsApiError';
  }
}

function goalsError(status: number, action: string): GoalsApiError {
  const message =
    status === 401
      ? 'Your session has expired. Sign in again to manage your goal.'
      : status === 404
        ? 'No active goal or target found.'
        : status === 409
          ? 'Complete your profile before setting a goal.'
          : status === 422
            ? 'That goal or override value is not valid.'
            : `Could not ${action} (status ${status}).`;
  return new GoalsApiError(status, message);
}

/**
 * Create or replace the caller's active goal and get the computed target reveal.
 * Returns the new goal, the revealed calorie target, and clamp info. Call
 * `getTarget` afterward to read the full macro target read-model.
 */
export async function createGoal(
  session: GoalsSession,
  payload: GoalTargetRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<GoalTargetResponse> {
  return request<GoalTargetResponse>(
    userScopedUrl(session, 'goal'),
    {
      method: 'POST',
      headers: authHeaders(session),
      body: JSON.stringify(payload),
      action: 'create your goal',
      onError: goalsError,
      fetchImpl,
    },
  );
}

/**
 * Read the caller's current active goal (direction + recovered pace), or `null`
 * when there is none (FTY-189/FTY-190). A `404` — the fail-closed "no active
 * goal" (or cross-user) response — is mapped to `null` rather than thrown: an
 * absent goal is an expected state (a user who has not set one), and the caller
 * treats `null` as an unknown/neutral goal, never a guessed default. `pace` is
 * `null` for a maintain goal or a legacy goal off the band grid. Any other status
 * still throws a `GoalsApiError`.
 */
export async function getActiveGoal(
  session: GoalsSession,
  fetchImpl: typeof fetch = fetch,
): Promise<ActiveGoal | null> {
  try {
    const model = await request<ActiveGoal>(
      userScopedUrl(session, 'goal'),
      {
        method: 'GET',
        headers: authHeaders(session),
        action: 'load your goal',
        onError: goalsError,
        fetchImpl,
      },
    );
    return { direction: model.direction, pace: model.pace ?? null };
  } catch (error) {
    if (error instanceof GoalsApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/**
 * Read just the direction of the caller's active goal, or `null` when there is
 * none. A thin projection of {@link getActiveGoal} for callers (Trends) that only
 * colour by direction and never surface pace.
 */
export async function getActiveGoalDirection(
  session: GoalsSession,
  fetchImpl: typeof fetch = fetch,
): Promise<GoalDirection | null> {
  const goal = await getActiveGoal(session, fetchImpl);
  return goal ? goal.direction : null;
}

/**
 * Fetch the caller's active-goal target for today: calorie + macro targets
 * each with their effective value, derived value, and `derived | user` source.
 * Returns null-shaped read-model on 404 (no active target for today).
 */
export async function getTarget(
  session: GoalsSession,
  fetchImpl: typeof fetch = fetch,
): Promise<TargetReadModel> {
  return request<TargetReadModel>(
    userScopedUrl(session, 'target'),
    {
      method: 'GET',
      headers: authHeaders(session),
      action: 'load your target',
      onError: goalsError,
      fetchImpl,
    },
  );
}

/**
 * Set one or more manual overrides on the caller's target for today.
 * Returns the updated target read-model with `source: 'user'` for each
 * overridden component. An out-of-band value is rejected with `GoalsApiError`
 * status 422 — nothing is persisted.
 */
export async function setTargetOverride(
  session: GoalsSession,
  payload: TargetOverridePayload,
  fetchImpl: typeof fetch = fetch,
): Promise<TargetReadModel> {
  return request<TargetReadModel>(
    userScopedUrl(session, 'target/override'),
    {
      method: 'PUT',
      headers: authHeaders(session),
      body: JSON.stringify(payload),
      action: 'save your target override',
      onError: goalsError,
      fetchImpl,
    },
  );
}

/**
 * Reset one or more manual overrides on the caller's target for today back to
 * the derived value. Pass `targets` to reset specific overrides; omit to reset
 * all in-force overrides. Idempotent.
 */
export async function resetTargetOverride(
  session: GoalsSession,
  targets?: OverridableTargetKey[],
  fetchImpl: typeof fetch = fetch,
): Promise<TargetReadModel> {
  const body = targets ? JSON.stringify({ targets }) : JSON.stringify({});
  return request<TargetReadModel>(
    userScopedUrl(session, 'target/override/reset'),
    {
      method: 'POST',
      headers: authHeaders(session),
      body,
      action: 'reset your target',
      onError: goalsError,
      fetchImpl,
    },
  );
}
