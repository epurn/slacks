/**
 * FTY-204: Focused tests for the correction sheet's extracted error/format
 * helpers. The behaviour is also exercised through CorrectionSheet.test.tsx; this
 * pins the pure functions directly now that they carry standalone responsibility.
 */

import { CorrectionsApiError } from "@/api/corrections";
import { DerivedItemApiError } from "@/api/derivedItems";

import { formatAmount, messageForError, SEARCH_DEBOUNCE_MS } from "./helpers";

describe("messageForError", () => {
  it("passes through a CorrectionsApiError message verbatim", () => {
    const err = new CorrectionsApiError(422, "That correction couldn't be applied.");
    expect(messageForError(err, "apply that match")).toBe(
      "That correction couldn't be applied.",
    );
  });

  it("passes through a DerivedItemApiError message verbatim", () => {
    const err = new DerivedItemApiError(422, "That value couldn't be saved.");
    expect(messageForError(err, "save that override")).toBe(
      "That value couldn't be saved.",
    );
  });

  it("falls back to a nonjudgmental connection message for unknown errors", () => {
    expect(messageForError(new Error("network down"), "adjust the amount")).toBe(
      "We couldn't adjust the amount. Check your connection and try again.",
    );
  });

  it("never echoes an unknown error's own message (privacy: no value leak)", () => {
    const msg = messageForError(new Error("calories=9999999 rejected"), "load alternatives");
    expect(msg).not.toContain("9999999");
    expect(msg).toContain("load alternatives");
  });
});

describe("formatAmount", () => {
  it("renders an em dash for null", () => {
    expect(formatAmount(null)).toBe("—");
  });

  it("omits decimals for an integral amount", () => {
    expect(formatAmount(2)).toBe("2");
  });

  it("keeps one decimal for a fractional amount", () => {
    expect(formatAmount(1.5)).toBe("1.5");
  });
});

describe("SEARCH_DEBOUNCE_MS", () => {
  it("is the 300ms typing-pause window that bounds search fan-out", () => {
    expect(SEARCH_DEBOUNCE_MS).toBe(300);
  });
});
