/**
 * Focused tests for the onboarding wizard's error helper (FTY-206).
 *
 * `errorMessage` was extracted from `OnboardingScreen.tsx` into the wizard hook
 * module. The full save flow is covered end-to-end by `OnboardingScreen.test.tsx`;
 * this unit test pins the three branches of the status-derived message directly:
 * surface the API message for goal/profile errors, and a calm generic fallback
 * (never a stack or body leak) for anything else.
 */

import { GoalsApiError } from "@/api/goals";
import { ProfileApiError } from "@/api/profile";

import { errorMessage } from "./useOnboardingWizard";

describe("errorMessage", () => {
  it("surfaces a GoalsApiError message", () => {
    expect(
      errorMessage(new GoalsApiError(409, "That goal conflicts with an existing one.")),
    ).toBe("That goal conflicts with an existing one.");
  });

  it("surfaces a ProfileApiError message", () => {
    expect(errorMessage(new ProfileApiError(422, "Invalid height."))).toBe(
      "Invalid height.",
    );
  });

  it("falls back to a calm generic message for a plain network error", () => {
    expect(errorMessage(new Error("network down"))).toBe(
      "Could not save. Check your connection and try again.",
    );
  });

  it("falls back to the generic message for a non-Error value", () => {
    expect(errorMessage("boom")).toBe(
      "Could not save. Check your connection and try again.",
    );
  });
});
