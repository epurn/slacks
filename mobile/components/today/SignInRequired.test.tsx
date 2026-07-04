import React from "react";

import { DISPLAY_FONT_FAMILY, typeScale } from "@/theme";
import { SignInRequired } from "./SignInRequired";
import { mount } from "./todayTestUtils";

function flattenedStyle(style: unknown): Record<string, unknown> {
  const styles: Record<string, unknown>[] = Array.isArray(style) ? style : [style];
  return Object.assign({}, ...styles);
}

describe("SignInRequired", () => {
  it("renders the gated headline through DisplayText at typeScale.title2Large", () => {
    const tree = mount(<SignInRequired insetTop={47} />);
    const headline = tree.root.find(
      (n) =>
        (n.type as unknown as string) === "Text" &&
        n.props.accessibilityRole === "header" &&
        n.props.children === "Sign in to see your day",
    );
    const style = flattenedStyle(headline.props.style);
    expect(style.fontSize).toBe(typeScale.title2Large);
    expect(style.fontFamily).toBe(DISPLAY_FONT_FAMILY);
  });

  it("still renders the explanatory body copy", () => {
    const tree = mount(<SignInRequired insetTop={47} />);
    const body = tree.root.findAll(
      (n) => typeof n.props.children === "string" && n.props.children.includes("stored privately"),
    );
    expect(body.length).toBeGreaterThan(0);
  });
});
