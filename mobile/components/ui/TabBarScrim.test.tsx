import { StyleSheet } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { TabBarScrim } from "./TabBarScrim";
import { ThemeProvider } from "@/theme";

// The tab-bar dimming fade (FTY-185). Unlike the native expo-blur material, this
// scrim is drawn by the app as plain Views with a surface-colour opacity ramp,
// so its fade is fully observable here — the machine-assertable half of the
// "scrolled content fades/dims beneath the bar; text is not legible through the
// tab labels" requirement.

function render(override: "light" | "dark", height = 130): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider override={override}>
        <TabBarScrim height={height} />
      </ThemeProvider>,
    );
  });
  return tree;
}

// Host View instances only (`type` is the string tag) — react-test-renderer
// surfaces both the composite `View` and its host child, each carrying the same
// testID, so filter to the host to avoid duplicate bands.
function bandNodes(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      typeof n.type === "string" &&
      typeof n.props.testID === "string" &&
      n.props.testID.startsWith("tab-bar-scrim-band-"),
  );
}

function bandOpacities(tree: ReactTestRenderer): number[] {
  return bandNodes(tree).map((band) => {
      const style = StyleSheet.flatten(band.props.style) as { opacity?: number };
      return style.opacity as number;
    });
}

describe("TabBarScrim (FTY-185 dimming fade)", () => {
  it("ramps a transparent→opaque fade so content dims into the surface", () => {
    const tree = render("light");

    const opacities = bandOpacities(tree);
    expect(opacities.length).toBeGreaterThan(1);
    // Fully legible at the top, fully faded into the surface at the bottom.
    expect(opacities[0]).toBe(0);
    expect(opacities[opacities.length - 1]).toBe(1);
    // Monotonic increase — a real gradient, not a single flat scrim.
    for (let i = 1; i < opacities.length; i += 1) {
      expect(opacities[i]).toBeGreaterThan(opacities[i - 1]);
    }
  });

  it("pins to the bottom at the requested height and never intercepts touches", () => {
    const tree = render("light", 130);

    const scrim = tree.root.find((n) => n.props.testID === "tab-bar-scrim");
    expect(scrim.props.pointerEvents).toBe("none");
    const style = StyleSheet.flatten(scrim.props.style) as {
      position?: string;
      bottom?: number;
      height?: number;
    };
    expect(style.position).toBe("absolute");
    expect(style.bottom).toBe(0);
    expect(style.height).toBe(130);
  });

  it("fades into the correct surface colour in light and dark", () => {
    for (const [mode, surface] of [
      ["light", "#F2F2F7"],
      ["dark", "#1C1C1E"],
    ] as const) {
      const tree = render(mode);
      const bands = bandNodes(tree);
      for (const band of bands) {
        const style = StyleSheet.flatten(band.props.style) as {
          backgroundColor?: string;
        };
        expect(style.backgroundColor).toBe(surface);
      }
    }
  });
});
