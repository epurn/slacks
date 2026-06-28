import {
  connectionBannerPresentation,
  isUnreachableError,
} from "./reachability";
import { LogEventApiError } from "@/api/logEvents";

describe("isUnreachableError", () => {
  it("treats a network-layer failure as unreachable", () => {
    expect(isUnreachableError(new TypeError("Network request failed"))).toBe(
      true,
    );
  });

  it("treats an HTTP error (server answered) as reachable", () => {
    expect(isUnreachableError(new LogEventApiError(422, "bad"))).toBe(false);
    expect(isUnreachableError(new LogEventApiError(401, "expired"))).toBe(false);
  });
});

describe("connectionBannerPresentation", () => {
  it("is hidden when online and caught up", () => {
    expect(connectionBannerPresentation("online", 0).visible).toBe(false);
  });

  it("shows a calm offline note that never reads as an error", () => {
    const p = connectionBannerPresentation("offline", 0);
    expect(p.visible).toBe(true);
    expect(p.tone).toBe("muted");
    expect(p.label.toLowerCase()).toContain("offline");
    // Calm tone: never an alarm word.
    expect(p.label.toLowerCase()).not.toContain("error");
    expect(p.label.toLowerCase()).not.toContain("failed");
  });

  it("pluralises the queued count in words (not colour-only)", () => {
    expect(connectionBannerPresentation("offline", 1).label).toContain(
      "1 entry queued",
    );
    expect(connectionBannerPresentation("offline", 3).label).toContain(
      "3 entries queued",
    );
  });

  it("shows a reconnecting note while draining", () => {
    const p = connectionBannerPresentation("reconnecting", 2);
    expect(p.visible).toBe(true);
    expect(p.label).toContain("Reconnecting");
    expect(p.label).toContain("2 entries queued");
  });

  it("shows a brief sending note when online with a backlog", () => {
    const p = connectionBannerPresentation("online", 2);
    expect(p.visible).toBe(true);
    expect(p.label).toContain("Sending");
  });
});
