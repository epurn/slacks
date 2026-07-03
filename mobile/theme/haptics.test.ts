import * as Haptics from "expo-haptics";

import {
  correctionSavedHaptic,
  entryResolvedHaptic,
  targetReachedHaptic,
} from "./haptics";

// The three signature-beat haptics wrap expo-haptics. Assert each maps to the
// designed feedback and that a rejecting native call is swallowed (a device
// without a Taptic Engine must never surface an error).
describe("signature-beat haptics", () => {
  let impact: jest.SpyInstance;
  let notify: jest.SpyInstance;

  beforeEach(() => {
    impact = jest
      .spyOn(Haptics, "impactAsync")
      .mockResolvedValue(undefined);
    notify = jest
      .spyOn(Haptics, "notificationAsync")
      .mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("beat 1 — entry resolved fires a light impact (soft tap)", () => {
    entryResolvedHaptic();
    expect(impact).toHaveBeenCalledTimes(1);
    expect(impact).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light);
    expect(notify).not.toHaveBeenCalled();
  });

  it("beat 2 — correction saved fires a success notification", () => {
    correctionSavedHaptic();
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      Haptics.NotificationFeedbackType.Success,
    );
    expect(impact).not.toHaveBeenCalled();
  });

  it("beat 3 — target reached fires a success notification", () => {
    targetReachedHaptic();
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      Haptics.NotificationFeedbackType.Success,
    );
  });

  it("swallows a rejected native haptic call (no unhandled rejection)", async () => {
    impact.mockRejectedValueOnce(new Error("no taptic engine"));
    expect(() => entryResolvedHaptic()).not.toThrow();
    // Let the swallowed rejection settle without surfacing.
    await Promise.resolve();
  });
});
