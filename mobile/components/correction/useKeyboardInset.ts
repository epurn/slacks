/**
 * FTY-404: Track the software keyboard's height so a scroll container can inset
 * its content by the *real* platform keyboard frame — never a hard-coded offset.
 *
 * The OS reports the keyboard's end frame in its keyboard events; we read that
 * height and hand it back so callers can pad the scrollable region by exactly
 * the space the keyboard occupies. Returns `0` while the keyboard is hidden.
 *
 * iOS emits the `keyboardWillShow` / `keyboardWillHide` pair ahead of the
 * animation (so avoidance settles before the keyboard finishes sliding); other
 * platforms fire `keyboardDidShow` / `keyboardDidHide` reliably. Either way the
 * value is the genuine keyboard height, so keyboard-avoidance holds across every
 * supported device height with no magic numbers.
 */

import { useEffect, useState } from "react";
import { Keyboard, Platform, type KeyboardEvent } from "react-native";

export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    const onShow = (event: KeyboardEvent) => {
      setInset(event?.endCoordinates?.height ?? 0);
    };
    const onHide = () => setInset(0);

    const showEvent = Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent = Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";

    const showSub = Keyboard.addListener(showEvent, onShow);
    const hideSub = Keyboard.addListener(hideEvent, onHide);
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  return inset;
}
