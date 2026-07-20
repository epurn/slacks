import { normalizeText } from "./normalizeText";

describe("normalizeText", () => {
  it("case-folds and collapses whitespace", () => {
    expect(normalizeText("  Black   Coffee ")).toBe("black coffee");
    expect(normalizeText("BLACK COFFEE")).toBe("black coffee");
  });

  it("strips diacritics via NFKD decomposition", () => {
    expect(normalizeText("Café con leche")).toBe("cafe con leche");
    expect(normalizeText("jalapeño")).toBe("jalapeno");
  });

  it("returns the empty string for whitespace-only or mark-only input", () => {
    expect(normalizeText("   ")).toBe("");
    expect(normalizeText("\t\n")).toBe("");
  });

  it("is idempotent", () => {
    const once = normalizeText("ÉGG  Whites");
    expect(normalizeText(once)).toBe(once);
  });
});
