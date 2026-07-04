import { Animated } from "react-native";
import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { CalorieHero } from "./CalorieHero";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { targetReachedHaptic } from "@/theme/haptics";
import { displayTracking } from "@/theme";

// The signature-beat haptics are mocked so the target-reached beat can be
// asserted without a native Taptic Engine.
jest.mock("@/theme/haptics", () => ({
  targetReachedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
}));

const mockTargetReachedHaptic = targetReachedHaptic as jest.MockedFunction<
  typeof targetReachedHaptic
>;

// A fake Animated driver that finishes synchronously, so no animation loop keeps
// ticking after a test tears down (which otherwise logs "Jest environment torn
// down" noise). Tests still assert on spring/timing being called via the spies.
const FAKE_ANIM = { start: (cb?: (r: { finished: boolean }) => void) => cb?.({ finished: true }), stop: () => {} };
let springSpy: jest.SpyInstance;

beforeEach(() => {
  // Reduce Motion off by default so the hero bar takes its spring path.
  mockReduceMotion(false);
  mockTargetReachedHaptic.mockClear();
  springSpy = jest.spyOn(Animated, "spring").mockReturnValue(FAKE_ANIM as never);
  jest.spyOn(Animated, "timing").mockReturnValue(FAKE_ANIM as never);
});

afterEach(() => {
  jest.restoreAllMocks();
});

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

describe("CalorieHero — summary availability", () => {
  it("does not present an unavailable summary as a real no-target state", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <CalorieHero
          consumed={0}
          target={null}
          summaryState="unavailable"
        />,
      );
    });

    const text = allText(tree!);
    expect(text).toContain("Summary unavailable");
    expect(text).not.toContain("No target set");
    expect(allA11yLabels(tree!).some((l) => l.includes("summary unavailable"))).toBe(
      true,
    );
  });

  it("keeps the load-state shell honest while summary data is pending", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={0} target={null} summaryState="loading" />);
    });

    const text = allText(tree!);
    expect(text).toContain("Loading summary");
    expect(text).not.toContain("No target set");
    expect(allA11yLabels(tree!).some((l) => l.includes("summary loading"))).toBe(true);
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
    // The fill now eases via an animated width (FTY-181); an empty day resolves
    // to a 0%-wide amber fill (empty track).
    const width = flattenedStyle(fill.props.style).width as {
      __getValue: () => string;
    };
    expect(width.__getValue()).toBe("0%");
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

describe("CalorieHero — beat 3: target reached", () => {
  it("does not fire on mount, even when the day opens already over target", () => {
    act(() => {
      render(<CalorieHero consumed={2100} target={2000} />);
    });
    expect(mockTargetReachedHaptic).not.toHaveBeenCalled();
  });

  it("fires once when intake crosses the target (a live crossing)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1800} target={2000} />);
    });
    expect(mockTargetReachedHaptic).not.toHaveBeenCalled();

    act(() => {
      tree!.update(<CalorieHero consumed={2050} target={2000} />);
    });
    expect(mockTargetReachedHaptic).toHaveBeenCalledTimes(1);
  });

  it("does not re-fire on further re-renders while staying over target", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1800} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={2050} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={2200} target={2000} />);
    });
    expect(mockTargetReachedHaptic).toHaveBeenCalledTimes(1);
  });

  it("re-arms after dropping back under, so a second crossing beats again", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1800} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={2050} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={1500} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={2100} target={2000} />);
    });
    expect(mockTargetReachedHaptic).toHaveBeenCalledTimes(2);
  });

  it("still fires the haptic under Reduce Motion (a haptic is not motion)", () => {
    mockReduceMotion(true);
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1800} target={2000} />);
    });
    act(() => {
      tree!.update(<CalorieHero consumed={2050} target={2000} />);
    });
    expect(mockTargetReachedHaptic).toHaveBeenCalledTimes(1);
  });
});

describe("CalorieHero — hero bar easing", () => {
  it("eases the fill with a spring when Reduce Motion is off", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={800} target={2000} />);
    });
    springSpy.mockClear();
    act(() => {
      tree!.update(<CalorieHero consumed={1600} target={2000} />);
    });
    // The bar fill (amber + coral segments) animates toward the new fraction.
    expect(springSpy).toHaveBeenCalled();
  });

  it("sets the fill value without a spring under Reduce Motion", () => {
    mockReduceMotion(true);
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={800} target={2000} />);
    });
    springSpy.mockClear();
    act(() => {
      tree!.update(<CalorieHero consumed={1600} target={2000} />);
    });
    expect(springSpy).not.toHaveBeenCalled();
  });
});

describe("CalorieHero — display face", () => {
  it("renders the hero numeral through the DisplayText tracking (ThemedNumber)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<CalorieHero consumed={1240} target={2000} />);
    });

    const heroNumeral = tree!.root.find(
      (n) => (n.type as unknown as string) === "Text" && n.props.children === "1,240",
    );
    const style = flattenedStyle(heroNumeral.props.style);
    expect(style.letterSpacing).toBe(displayTracking);
    expect(style.fontVariant).toEqual(["tabular-nums"]);
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
