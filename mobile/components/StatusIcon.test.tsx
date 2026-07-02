import React from "react";
import { act, create } from "react-test-renderer";

import { StatusIcon } from "./StatusIcon";
import { ThemeProvider } from "@/theme/ThemeContext";
import { darkPalette, lightPalette } from "@/theme/colors";

function renderIcon(scheme: "light" | "dark") {
  let tree: ReturnType<typeof create>;
  act(() => {
    tree = create(
      <ThemeProvider override={scheme}>
        <StatusIcon status="needs_clarification" />
      </ThemeProvider>,
    );
  });
  return tree!;
}

// FTY-177: the glyph used to hardcode `#3A3A3C`, a near-black that vanished on
// the dark charcoal surface. It must now come from the theme's AA-compliant
// `textSecondary` token in both palettes, never a hardcoded hex.
describe("StatusIcon", () => {
  it("colours the glyph from the theme's textSecondary token in light mode", () => {
    const tree = renderIcon("light");
    const icon = tree.root.findByProps({ accessibilityRole: "image" });
    const flatStyle = [icon.props.style].flat();
    expect(flatStyle).toContainEqual({ color: lightPalette.textSecondary });
    expect(flatStyle.some((s) => s && s.color === "#3A3A3C")).toBe(false);
  });

  it("colours the glyph from the theme's textSecondary token in dark mode", () => {
    const tree = renderIcon("dark");
    const icon = tree.root.findByProps({ accessibilityRole: "image" });
    const flatStyle = [icon.props.style].flat();
    expect(flatStyle).toContainEqual({ color: darkPalette.textSecondary });
    expect(flatStyle.some((s) => s && s.color === "#3A3A3C")).toBe(false);
  });

  it("pairs the glyph with an accessibility label", () => {
    const tree = renderIcon("light");
    const icon = tree.root.findByProps({ accessibilityRole: "image" });
    expect(icon.props.accessibilityLabel).toBe("Needs a quick detail");
  });
});
