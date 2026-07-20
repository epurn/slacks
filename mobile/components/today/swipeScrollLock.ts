import { createContext, useContext } from "react";

/**
 * Lock/unlock the enclosing Today scroll container for the duration of an active
 * horizontal swipe (FTY-417). A {@link SwipeableRow} calls this with `true` the
 * moment its horizontal pan is granted and `false` when the gesture ends, so the
 * timeline's `ScrollView` stops scrolling and cannot reclaim the pan and snap the
 * delete reveal shut mid-swipe.
 */
export type SetScrollLocked = (locked: boolean) => void;

/**
 * Provided by the Today `ScrollView` shell; its value locks the scroll while a
 * row swipe is active. `null` outside a provider — an isolated `SwipeableRow`
 * (e.g. in a unit test, or any future non-scrolling host) simply skips the
 * coordination, and the row's own `onPanResponderTerminationRequest` still keeps
 * the gesture from being reclaimed.
 */
export const SwipeScrollLockContext = createContext<SetScrollLocked | null>(null);

/** Read the active scroll-lock setter, or `null` when there is no provider. */
export function useSwipeScrollLock(): SetScrollLocked | null {
  return useContext(SwipeScrollLockContext);
}
