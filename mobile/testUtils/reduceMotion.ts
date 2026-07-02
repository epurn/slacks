import { AccessibilityInfo } from "react-native";

function immediateReduceMotion(enabled: boolean): Promise<boolean> {
  return {
    then(onFulfilled?: ((value: boolean) => unknown) | null) {
      onFulfilled?.(enabled);
      return Promise.resolve(enabled);
    },
  } as Promise<boolean>;
}

export function mockReduceMotion(enabled: boolean): void {
  jest
    .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
    .mockReturnValue(immediateReduceMotion(enabled));
  jest
    .spyOn(AccessibilityInfo, "addEventListener")
    .mockReturnValue({ remove: jest.fn() } as never);
}
