import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { CalorieHero } from "./CalorieHero";

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => !!n.props.accessibilityLabel)
    .map((n) => n.props.accessibilityLabel as string);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function flattenedStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return Object.assign({}, ...style.map(flattenedStyle));
  }
  return typeof style === "object" && style !== null
    ? (style as Record<string, unknown>)
    : {};
}

describe("CalorieHero — under budget", () => {
  it("shows consumed, target, percent, and remaining", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1240} target={2000} />);
    });

    const text = allText(tree!);
    expect(text).toContain("1,240 / 2,000 kcal · 62%");
    expect(text).toContain("1,240");
    expect(text).toContain("2,000");
    expect(text).toContain("62%");
    expect(text).toContain("760");
    expect(text).toContain("to go");
  });

  it("provides a combined VoiceOver label with all hero figures", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1240} target={2000} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("1,240 of 2,000 kcal"))).toBe(true);
    expect(labels.some((l) => l.includes("62 percent"))).toBe(true);
    expect(labels.some((l) => l.includes("760 remaining"))).toBe(true);
  });
});

describe("CalorieHero — over budget", () => {
  it("shows the coral 'X over' text (not color alone)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={2500} target={2000} />);
    });

    const text = allText(tree!);
    expect(text).toContain("500");
    expect(text).toContain("over");
    // Must NOT show "to go" when over budget
    expect(text).not.toContain("to go");
  });

  it("VoiceOver label mentions over-budget clearly", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={2400} target={2000} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("400 over budget"))).toBe(true);
  });
});

describe("CalorieHero — null target", () => {
  it("shows consumed calories and no-target copy, no crash or divide-by-zero", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1240} target={null} />);
    });

    const text = allText(tree!);
    expect(text).toContain("1,240");
    expect(text).not.toContain("undefined");
    expect(text).not.toContain("NaN");
    expect(text).not.toContain("Infinity");
  });

  it("VoiceOver label mentions no target set", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={850} target={null} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("no target set"))).toBe(true);
  });
});

describe("CalorieHero — empty state", () => {
  it("shows 0 consumed with full budget, empty bar track, calm tone", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={0} target={2000} hasIntake={false} />);
    });

    const text = allText(tree!);
    expect(text).toContain("0 / 2,000 kcal · 2,000 to go");
    expect(text).not.toContain("0%");
    const fill = tree!.root.findByProps({ testID: "calorie-hero-bar-fill" });
    expect(flattenedStyle(fill.props.style).flex).toBe(0);
  });

  it("VoiceOver label says 2,000 remaining", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={0} target={2000} hasIntake={false} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("2,000 remaining"))).toBe(true);
    expect(labels.some((l) => l.includes("0 percent"))).toBe(false);
  });

  it("keeps a genuine 0-kcal logged day distinct from an unlogged day", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={0} target={2000} hasIntake />);
    });

    const text = allText(tree!);
    expect(text).toContain("0 / 2,000 kcal · 0%");
    expect(text).toContain("2,000 to go");
  });
});

describe("CalorieHero — accessibility", () => {
  it("the hero is a single accessible unit (not fragmented across children)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1500} target={2000} />);
    });

    // The outer container has the combined a11y label
    const labels = allA11yLabels(tree!);
    const heroLabel = labels.find((l) => l.includes("of 2,000 kcal"));
    expect(heroLabel).toBeDefined();
    // Includes percent and remaining in one label
    expect(heroLabel).toContain("75 percent");
    expect(heroLabel).toContain("500 remaining");
  });
});
