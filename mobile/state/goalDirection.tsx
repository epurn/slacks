/**
 * Cross-screen goal-direction seam (FTY-189).
 *
 * There is no `GET /goal` read endpoint (`docs/contracts/goals-target-reveal.md`
 * only exposes create) and no `direction` field on the daily-summary / target
 * read-models, so a goal's direction (lose / maintain / gain) is only ever known
 * from the screen that just created or edited it (`SettingsScreen`,
 * `OnboardingScreen` — both receive it back on the `POST /goal` response).
 * Trends needs that direction to color the weight delta by progress-toward-goal
 * rather than "down = good" (ux-design §4b).
 *
 * The value is held in memory for the current app session AND persisted on
 * device (state/goalDirectionStore.ts) so it survives a cold launch: a returning
 * user who reopens the app (session hydrated from the keychain, never a fresh
 * goal save) still gets Trends colored by their real goal direction instead of
 * the `loss` fallback. On launch the provider hydrates the persisted direction
 * for the signed-in user; when a goal is saved it persists the new direction.
 * The persisted record is keyed by `userId`, so a different account never
 * inherits a stale direction. `clearGoalDirection` (called on sign-out) resets
 * the in-memory value; the on-device record is left for the same account to
 * rehydrate and is userId-guarded against cross-account reads.
 *
 * Screens that read it (Trends) treat "unknown" as their own sensible default;
 * screens that know it (Settings, Onboarding) call `setGoalDirection` right
 * after a successful goal save.
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

import type { GoalDirection } from "@/api/goals";
import { useSession } from "@/state/session";
import {
  secureGoalDirectionStore,
  type GoalDirectionStore,
} from "@/state/goalDirectionStore";

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
 * Provides the goal direction to the tree, hydrated from and persisted to the
 * on-device store for the signed-in user. Mount once, near the root, inside
 * `SessionProvider` (it reads the session to key persistence by user). `store`
 * is injectable for tests.
 */
export function GoalDirectionProvider({
  children,
  store = secureGoalDirectionStore,
}: {
  children: ReactNode;
  store?: GoalDirectionStore;
}) {
  const session = useSession();
  const userId = session?.userId ?? null;
  const [goalDirection, setGoalDirectionState] = useState<GoalDirection | null>(null);

  // Hydrate the persisted direction for the signed-in user (e.g. cold launch,
  // before Settings/Onboarding reports one this session). A record for a
  // different account is ignored, and a value already known this session is
  // never clobbered by the (possibly older) persisted one.
  useEffect(() => {
    if (!userId) return;
    let active = true;
    void store.load().then((record) => {
      if (!active || record === null || record.userId !== userId) return;
      setGoalDirectionState((current) => current ?? record.direction);
    });
    return () => {
      active = false;
    };
  }, [userId, store]);

  const setGoalDirection = useCallback(
    (direction: GoalDirection) => {
      setGoalDirectionState(direction);
      if (userId) void store.save(userId, direction);
    },
    [userId, store],
  );

  const clearGoalDirection = useCallback(() => {
    // Reset the in-memory value only (e.g. sign-out): the on-device record is
    // userId-keyed and guarded on read, so the same account rehydrates it and a
    // different account never sees it.
    setGoalDirectionState(null);
  }, []);

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
