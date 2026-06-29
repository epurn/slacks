/**
 * Tests for the signed-out + onboarding routing decision (FTY-091 + FTY-103).
 *
 * Covers the four-state gate (connect → sign-in → onboarding → app) with no
 * reachable dead-end, the hydration hold that prevents a wrong-screen flash,
 * and the loop-free onboarding routing that must not re-run for an established
 * user.
 */

import {
  resolveAuthRedirect,
  resolveOnboardingStatus,
  type AuthRouteInput,
} from "./authRouting";

const URL = "https://home.example.net";

/**
 * A fully-ready, signed-in, onboarding-complete, not-on-a-gate-screen
 * baseline; override per case.
 */
function input(over: Partial<AuthRouteInput> = {}): AuthRouteInput {
  return {
    connectionStatus: "ready",
    connection: URL,
    sessionStatus: "ready",
    session: { serverUrl: URL, token: "h.s", userId: "u1" },
    onboardingStatus: "complete",
    atConnect: false,
    atSignin: false,
    atOnboarding: false,
    ...over,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Hydration hold
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — hydration hold", () => {
  it("holds while the connection is still hydrating", () => {
    expect(
      resolveAuthRedirect(
        input({
          connectionStatus: "hydrating",
          connection: null,
          session: null,
        }),
      ),
    ).toBeNull();
  });

  it("holds while the session is still hydrating", () => {
    expect(
      resolveAuthRedirect(
        input({ sessionStatus: "hydrating", session: null }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// No server connected
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — no server connected", () => {
  it("routes to connect when signed out with no server", () => {
    expect(
      resolveAuthRedirect(
        input({ connection: null, session: null, onboardingStatus: "checking" }),
      ),
    ).toBe("/connect");
  });

  it("does not redirect when already on the connect screen", () => {
    expect(
      resolveAuthRedirect(
        input({
          connection: null,
          session: null,
          onboardingStatus: "checking",
          atConnect: true,
        }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Connected but signed out
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — connected but signed out", () => {
  it("routes to sign-in when a server is connected but there is no session", () => {
    expect(
      resolveAuthRedirect(
        input({ session: null, onboardingStatus: "checking" }),
      ),
    ).toBe("/signin");
  });

  it("does not redirect when already on the sign-in screen", () => {
    expect(
      resolveAuthRedirect(
        input({
          session: null,
          onboardingStatus: "checking",
          atSignin: true,
        }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Signed in — onboarding check still pending
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — signed in, onboarding checking", () => {
  it("holds while the onboarding status is still being checked", () => {
    expect(
      resolveAuthRedirect(input({ onboardingStatus: "checking" })),
    ).toBeNull();
  });

  it("holds even if the user is on the sign-in screen during the check", () => {
    expect(
      resolveAuthRedirect(
        input({ onboardingStatus: "checking", atSignin: true }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Signed in — onboarding undetermined (transient probe failure)
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — signed in, onboarding undetermined", () => {
  it("holds when the onboarding check could not reach a verdict", () => {
    expect(
      resolveAuthRedirect(input({ onboardingStatus: "undetermined" })),
    ).toBeNull();
  });

  it("does NOT route a returning user into onboarding on a transient failure", () => {
    // The whole point of the undetermined state: a network blip must never
    // shove a possibly-onboarded user into the wizard (which would overwrite
    // their active goal on re-completion).
    expect(
      resolveAuthRedirect(input({ onboardingStatus: "undetermined" })),
    ).not.toBe("/onboarding");
  });

  it("leaves a user already on the onboarding screen put (no flicker)", () => {
    expect(
      resolveAuthRedirect(
        input({ onboardingStatus: "undetermined", atOnboarding: true }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Signed in — onboarding incomplete
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — signed in, onboarding incomplete", () => {
  it("routes to onboarding when signed in with an incomplete profile/goal", () => {
    expect(
      resolveAuthRedirect(input({ onboardingStatus: "incomplete" })),
    ).toBe("/onboarding");
  });

  it("routes from the sign-in screen to onboarding (not Today) when incomplete", () => {
    expect(
      resolveAuthRedirect(
        input({ onboardingStatus: "incomplete", atSignin: true }),
      ),
    ).toBe("/onboarding");
  });

  it("stays on the onboarding screen when already there (no loop)", () => {
    expect(
      resolveAuthRedirect(
        input({ onboardingStatus: "incomplete", atOnboarding: true }),
      ),
    ).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Signed in — onboarding complete
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveAuthRedirect — signed in, onboarding complete", () => {
  it("stays put on a normal app screen (returning user)", () => {
    expect(resolveAuthRedirect(input())).toBeNull();
  });

  it("routes a signed-in user off the sign-in screen to Today", () => {
    expect(resolveAuthRedirect(input({ atSignin: true }))).toBe("/");
  });

  it("routes off the onboarding screen to Today when complete", () => {
    // Handles the case where the user completes onboarding and the status
    // updates to complete while they are still on the onboarding route.
    expect(
      resolveAuthRedirect(
        input({ onboardingStatus: "complete", atOnboarding: true }),
      ),
    ).toBe("/");
  });

  it("does not force a signed-in user off the connect screen (change server)", () => {
    expect(resolveAuthRedirect(input({ atConnect: true }))).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// resolveOnboardingStatus — classifying the two data-source probes
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveOnboardingStatus", () => {
  it("is complete only when both the profile and target are present", () => {
    expect(resolveOnboardingStatus("present", "present")).toBe("complete");
  });

  it("is incomplete when the profile is present but the target is absent (no goal yet)", () => {
    expect(resolveOnboardingStatus("present", "absent")).toBe("incomplete");
  });

  it("is incomplete when the target is present but the profile is absent/incomplete", () => {
    expect(resolveOnboardingStatus("absent", "present")).toBe("incomplete");
  });

  it("is incomplete when both are absent (a fresh user — definitive 404s)", () => {
    expect(resolveOnboardingStatus("absent", "absent")).toBe("incomplete");
  });

  it("is undetermined when the profile probe failed transiently", () => {
    // The reviewer's #2: a 5xx/network failure on the profile must NOT collapse
    // to 'incomplete' even though the target is genuinely set up.
    expect(resolveOnboardingStatus("unknown", "present")).toBe("undetermined");
  });

  it("is undetermined when the target probe failed transiently", () => {
    expect(resolveOnboardingStatus("present", "unknown")).toBe("undetermined");
  });

  it("is undetermined when both probes failed transiently", () => {
    expect(resolveOnboardingStatus("unknown", "unknown")).toBe("undetermined");
  });

  it("prefers undetermined over incomplete when one probe is absent but the other is unknown", () => {
    // A definitive 404 on one source plus an unknown on the other is still
    // 'couldn't tell' overall — never route to onboarding on a partial failure.
    expect(resolveOnboardingStatus("absent", "unknown")).toBe("undetermined");
    expect(resolveOnboardingStatus("unknown", "absent")).toBe("undetermined");
  });
});
