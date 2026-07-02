/**
 * Cross-screen goal-direction seam (FTY-189).
 *
 * A goal's direction (lose / maintain / gain) is not carried on the daily-summary
 * or target read-models, so Trends — which needs it to color the weight delta by
 * progress-toward-goal rather than "down = good" (ux-design §4b) — has two ways to
 * learn it, both routed through this provider so every consumer reads one value:
 *
 *   1. On sign-in / launch the provider **hydrates from the authoritative
 *      `GET /goal` read** (`getActiveGoalDirection`), so a returning user with an
 *      existing goal is coloured correctly after a cold launch — the fix for the
 *      "data-starved on restart" gap.
 *   2. `SettingsScreen` / `OnboardingScreen` call `setGoalDirection` right after a
 *      successful goal save (they receive the direction back on the `POST /goal`
 *      response), so an in-session create/edit updates immediately without waiting
 *      for a refetch. A same-session value is never clobbered by a slower hydrate.
 *
 * The value is in-memory and session-scoped — **not persisted to disk** — and
 * resets to unknown on sign-out and when the signed-in user changes, so a new
 * account never inherits a stale direction. Consumers treat "unknown" (`null`) as
 * **neutral** — no toward/away claim rather than a guessed default — so a user
 * whose goal can't be read (offline, or none set) is never mis-colored.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getActiveGoalDirection } from "@/api/goals";
import type { GoalDirection } from "@/api/goals";
import { toApiSession, useSession } from "@/state/session";
import type { ApiSession } from "@/state/session";

export interface GoalDirectionController {
  /** The most recently known goal direction this session, or `null` if unknown. */
  readonly goalDirection: GoalDirection | null;
  setGoalDirection(direction: GoalDirection): void;
  clearGoalDirection(): void;
}

// Deliberately non-throwing defaults (unlike `useSessionController`): most
// screens don't need this value and shouldn't be forced to mount a provider
// (or update every existing test) just because it exists somewhere in the tree.
const GoalDirectionContext = createContext<GoalDirectionController>({
  goalDirection: null,
  setGoalDirection: () => {},
  clearGoalDirection: () => {},
});

/**
 * Provides the session-scoped goal direction to the tree. Mount once, near the
 * root (under `SessionProvider`, whose session it reads to hydrate).
 *
 * `readActiveGoalDirection` is injectable for tests; it defaults to the live
 * `GET /goal` client.
 */
export function GoalDirectionProvider({
  children,
  readActiveGoalDirection = getActiveGoalDirection,
}: {
  children: ReactNode;
  readActiveGoalDirection?: (
    session: ApiSession,
  ) => Promise<GoalDirection | null>;
}) {
  const [goalDirection, setGoalDirectionState] = useState<GoalDirection | null>(null);
  const session = useSession();
  const userId = session?.userId ?? null;

  // Reset the known direction the instant the signed-in user changes (including
  // sign-out), so a prior account's direction never lingers before the async
  // hydrate below runs. Resetting during render — not in an effect — is React's
  // recommended way to adjust state on a prop/context change and avoids a stale
  // frame (https://react.dev/learn/you-might-not-need-an-effect).
  const [hydratedUserId, setHydratedUserId] = useState<string | null>(userId);
  if (userId !== hydratedUserId) {
    setHydratedUserId(userId);
    setGoalDirectionState(null);
  }

  const setGoalDirection = useCallback((direction: GoalDirection) => {
    setGoalDirectionState(direction);
  }, []);

  const clearGoalDirection = useCallback(() => {
    setGoalDirectionState(null);
  }, []);

  // Hydrate from the authoritative `GET /goal` read whenever the signed-in user
  // changes. The direction was already reset above, so this only *seeds* it — and
  // only if nothing fresher was set this session (e.g. an in-session goal
  // create/edit via `setGoalDirection`), so the hydrate never clobbers a newer
  // known value. A failed/absent read leaves it unknown (neutral).
  useEffect(() => {
    if (!session) return;
    let active = true;
    const apiSession = toApiSession(session);
    void readActiveGoalDirection(apiSession)
      .then((direction) => {
        if (!active || direction === null) return;
        setGoalDirectionState((prev) => (prev === null ? direction : prev));
      })
      .catch(() => {
        // Best-effort: an unreachable read leaves the direction unknown rather
        // than guessing one.
      });
    return () => {
      active = false;
    };
    // `userId` is the identity that gates a refetch; `session` is read inside.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, readActiveGoalDirection]);

  const value = useMemo<GoalDirectionController>(
    () => ({ goalDirection, setGoalDirection, clearGoalDirection }),
    [goalDirection, setGoalDirection, clearGoalDirection],
  );

  return (
    <GoalDirectionContext.Provider value={value}>
      {children}
    </GoalDirectionContext.Provider>
  );
}

/** The most recently known goal direction this session, or `null` if unknown. */
export function useGoalDirection(): GoalDirection | null {
  return useContext(GoalDirectionContext).goalDirection;
}

/** The full controller — `SettingsScreen`/`OnboardingScreen` call this after a goal save. */
export function useGoalDirectionController(): GoalDirectionController {
  return useContext(GoalDirectionContext);
}
