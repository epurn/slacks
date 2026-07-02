import React from "react";
import { act, create } from "react-test-renderer";

import { EntryRow } from "./EntryRow";
import type { LogEventDTO } from "@/api/logEvents";
import { ThemeProvider } from "@/theme/ThemeContext";

function baseEvent(overrides: Partial<LogEventDTO> = {}): LogEventDTO {
  return {
    id: "evt-1",
    user_id: "user-1",
    raw_text: "milk",
    status: "needs_clarification",
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    ...overrides,
  };
}

function renderRow(event: LogEventDTO, onPress?: () => void) {
  let tree: ReturnType<typeof create>;
  act(() => {
    tree = create(
      <ThemeProvider override="light">
        <EntryRow event={event} onPress={onPress} />
      </ThemeProvider>,
    );
  });
  return tree!;
}

function textContent(tree: ReturnType<typeof create>): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

// FTY-177: the needs_clarification row used to render a "needs a detail" tag
// AND a separate "Add a detail ›" CTA — two controls saying the same thing.
// This suite proves they collapsed into one affordance, plus the truncation
// hint and single a11y label the story requires.
describe("EntryRow needs_clarification row", () => {
  it("renders a single 'Add a detail' affordance, not the old duplicated tag + CTA", () => {
    const tree = renderRow(baseEvent());
    const text = textContent(tree);

    expect(text).toContain("Add a detail");
    // The old standalone "needs a detail" tag text is gone — the row's only
    // occurrence of that phrase now lives in the accessibilityLabel, not as
    // rendered body text.
    const bodyTextNodes = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(bodyTextNodes.some((t) => t === "needs a detail")).toBe(false);
  });

  it("keeps a single clear VoiceOver label with no double-announcement", () => {
    const tree = renderRow(baseEvent({ raw_text: "milk" }), jest.fn());
    // .find throws unless exactly one node matches — the row itself, not a
    // duplicated child announcement of the same state.
    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "milk, needs a detail, uncounted" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
  });

  it("is a single ≥44pt tap target that opens the clarify sheet via onPress", () => {
    const onPress = jest.fn();
    const tree = renderRow(baseEvent(), onPress);
    const row = tree.root.findByProps({ testID: "add-a-detail-row" });
    act(() => {
      row.props.onPress();
    });
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("stays visibly uncounted with a trailing em dash", () => {
    const tree = renderRow(baseEvent());
    expect(textContent(tree)).toContain("—");
  });

  it("shows a truncation hint for a long phrase that will clip at two lines", () => {
    const longText =
      "a large bowl of homemade granola with milk, blueberries, and honey drizzled on top";
    const tree = renderRow(baseEvent({ raw_text: longText }));
    expect(
      tree.root.findAllByProps({ testID: "add-a-detail-more-hint" }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(textContent(tree)).toContain("more");
  });

  it("omits the truncation hint for a short phrase", () => {
    const tree = renderRow(baseEvent({ raw_text: "milk" }));
    expect(
      tree.root.findAllByProps({ testID: "add-a-detail-more-hint" }).length,
    ).toBe(0);
  });
});
