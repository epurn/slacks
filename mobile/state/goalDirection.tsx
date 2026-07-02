/**
 * Cross-screen goal-direction seam (FTY-189).
 *
 * There is no `GET /goal` read endpoint (`docs/contracts/goals-target-reveal.md`
 * only exposes create) and no `direction` field on the daily-summary / target
 * read-models, so a goal's direction (lose / maintain / gain) is otherwise only
 * ever known transiently inside the screen that just created or edited it
 * (`SettingsScreen`, `OnboardingScreen` — both receive it back on the
 * `POST /goal` response). Trends needs that direction to color the weight
 * delta by progress-toward-goal rather than "down = good" (ux-design §4b).
 *
 * This is an in-memory, app-session-scoped value — not persisted to disk and
 * not fetched from the server — so it reflects the most recent goal
 * create/edit made *this session*. It resets to unknown on sign-out/sign-in so
 * a new account never inherits a stale direction. Screens that read it (Trends)
 * treat "unknown" as their own sensible default rather than crashing or
 * blocking; screens that know it (Settings, Onboarding) call `setGoalDirection`
 * right after a successful goal save.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { GoalDirection } from "@/api/goals";

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

/** Provides the session-scoped goal direction to the tree. Mount once, near the root. */
export function GoalDirectionProvider({ children }: { children: ReactNode }) {
  const [goalDirection, setGoalDirectionState] = useState<GoalDirection | null>(null);

  const setGoalDirection = useCallback((direction: GoalDirection) => {
    setGoalDirectionState(direction);
  }, []);

  const clearGoalDirection = useCallback(() => {
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
