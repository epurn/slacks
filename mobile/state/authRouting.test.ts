/**
 * Tests for the signed-out routing decision (FTY-091).
 *
 * Covers the three-state gate (connect → sign-in → app) with no reachable
 * dead-end, and the hydration hold that prevents a wrong-screen flash.
 */

import { resolveAuthRedirect, type AuthRouteInput } from "./authRouting";

const URL = "https://home.example.net";

/** A fully-ready, signed-in, not-on-a-gate-screen baseline; override per case. */
function input(over: Partial<AuthRouteInput> = {}): AuthRouteInput {
  return {
    connectionStatus: "ready",
    connection: URL,
    sessionStatus: "ready",
    session: { serverUrl: URL, token: "h.s", userId: "u1" },
    atConnect: false,
    atSignin: false,
    ...over,
  };
}

describe("resolveAuthRedirect — hydration hold", () => {
  it("holds while the connection is still hydrating", () => {
    expect(
      resolveAuthRedirect(
        input({ connectionStatus: "hydrating", connection: null, session: null }),
      ),
    ).toBeNull();
  });

  it("holds while the session is still hydrating", () => {
    expect(
      resolveAuthRedirect(input({ sessionStatus: "hydrating", session: null })),
    ).toBeNull();
  });
});

describe("resolveAuthRedirect — no server connected", () => {
  it("routes to connect when signed out with no server", () => {
    expect(
      resolveAuthRedirect(input({ connection: null, session: null })),
    ).toBe("/connect");
  });

  it("does not redirect when already on the connect screen", () => {
    expect(
      resolveAuthRedirect(
        input({ connection: null, session: null, atConnect: true }),
      ),
    ).toBeNull();
  });
});

describe("resolveAuthRedirect — connected but signed out", () => {
  it("routes to sign-in when a server is connected but there is no session", () => {
    expect(resolveAuthRedirect(input({ session: null }))).toBe("/signin");
  });

  it("does not redirect when already on the sign-in screen", () => {
    expect(
      resolveAuthRedirect(input({ session: null, atSignin: true })),
    ).toBeNull();
  });
});

describe("resolveAuthRedirect — signed in", () => {
  it("stays put on a normal app screen", () => {
    expect(resolveAuthRedirect(input())).toBeNull();
  });

  it("routes a signed-in user off the sign-in screen to Today", () => {
    expect(resolveAuthRedirect(input({ atSignin: true }))).toBe("/");
  });

  it("does not force a signed-in user off the connect screen (change server)", () => {
    expect(resolveAuthRedirect(input({ atConnect: true }))).toBeNull();
  });
});
