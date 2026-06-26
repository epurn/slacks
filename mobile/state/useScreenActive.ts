/**
 * Foreground/focus signal for focus-aware polling (FTY-032).
 *
 * Polling should run only while the screen is actually in front of the user:
 * the app is in the foreground AND the Today route is the focused screen.
 * Pausing otherwise is the battery/network requirement — a backgrounded or
 * navigated-away screen has no reason to keep hitting the API.
 *
 * These hooks are the seam that couples polling to the OS app state and the
 * navigator. `TodayScreen` takes the active signal as an injectable prop so its
 * tests drive start/stop/resume directly without a navigation container, the
 * same way `@/state/session` is the injected sign-in seam.
 */

import { useCallback, useEffect, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import { useFocusEffect } from "expo-router";

/** True while the OS reports the app in the foreground (`active`). */
export function useAppForeground(): boolean {
  const [foreground, setForeground] = useState(
    () => AppState.currentState === "active",
  );
  useEffect(() => {
    const subscription = AppState.addEventListener(
      "change",
      (state: AppStateStatus) => {
        setForeground(state === "active");
      },
    );
    return () => subscription.remove();
  }, []);
  return foreground;
}

/**
 * Whether the Today screen should poll: the app is in the foreground AND this
 * screen is the focused route. Resumes on the foreground/focus edge and pauses
 * on background/blur, so a finished estimate is picked up the moment the user
 * returns without polling while they are elsewhere.
 */
export function useScreenActive(): boolean {
  const foreground = useAppForeground();
  const [focused, setFocused] = useState(true);
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );
  return foreground && focused;
}
