import {
  act,
  create as render,
  type ReactTestRenderer,
} from "react-test-renderer";

import { ConnectionBanner } from "./ConnectionBanner";
import type { ReachabilityState } from "@/state/reachability";

function mount(
  state: ReachabilityState,
  queuedCount: number,
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <ConnectionBanner state={state} queuedCount={queuedCount} />,
    );
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("ConnectionBanner", () => {
  it("renders nothing when online and caught up (calm by default)", () => {
    const tree = mount("online", 0);
    expect(tree.toJSON()).toBeNull();
  });

  it("shows a calm offline message with an accessible label (not colour-only)", () => {
    const tree = mount("offline", 2);

    // The state is conveyed in words, both visibly and as the a11y label.
    expect(textContent(tree)).toContain("Offline");
    expect(textContent(tree)).toContain("2 entries queued");

    const labelled = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        n.props.accessibilityLabel.includes("Offline"),
    );
    expect(labelled.length).toBeGreaterThan(0);
  });

  it("announces politely and never as an alarm", () => {
    const tree = mount("offline", 1);
    const region = tree.root.find(
      (n) => n.props.accessibilityLiveRegion === "polite",
    );
    expect(region.props.accessibilityRole).not.toBe("alert");
  });

  it("reflects the reconnecting state", () => {
    const tree = mount("reconnecting", 1);
    expect(textContent(tree)).toContain("Reconnecting");
  });
});
