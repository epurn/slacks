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

function renderReadOnly(event: LogEventDTO) {
  let tree: ReturnType<typeof create>;
  act(() => {
    tree = create(
      <ThemeProvider override="light">
        <EntryRow event={event} readOnly />
      </ThemeProvider>,
    );
  });
  return tree!;
}

// FTY-199: on a read-only past-day timeline an unresolved needs_clarification /
// failed row must never show an affordance that looks tappable but is inert.
describe("EntryRow read-only past day (FTY-199)", () => {
  it("renders needs_clarification as a calm, non-interactive row — no 'Add a detail' chip", () => {
    const tree = renderReadOnly(baseEvent({ raw_text: "milk" }));

    // The row still renders and stays visibly uncounted…
    const row = tree.root.findByProps({ testID: "add-a-detail-row" });
    expect(textContent(tree)).toContain("—");
    // …but the accent CTA chip is gone and the row is not a tappable button.
    expect(textContent(tree)).not.toContain("Add a detail");
    expect(row.props.onPress).toBeUndefined();
    expect(row.props.accessibilityRole).not.toBe("button");
    // The state is still conveyed to VoiceOver on one element.
    expect(row.props.accessibilityLabel).toBe("milk, needs a detail, uncounted");
  });

  it("renders failed as a calm, non-interactive row — no Retry / Edit-as-text buttons", () => {
    const tree = renderReadOnly(baseEvent({ status: "failed", raw_text: "asdkfj" }));

    const row = tree.root.findByProps({ testID: "failed-parse-row" });
    expect(textContent(tree)).toContain("Couldn't read that");
    expect(tree.root.findAllByProps({ testID: "failed-retry" })).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "failed-edit-as-text" })).toHaveLength(0);
    expect(row.props.accessibilityLabel).toBe("asdkfj, couldn't read that, uncounted");
  });
});

describe("EntryRow — delete custom action (FTY-322)", () => {
  const deleteA11y = (onDelete: () => void) => ({
    accessibilityActions: [{ name: "delete", label: "Delete" }],
    onAccessibilityAction: (e: { nativeEvent: { actionName: string } }) => {
      if (e.nativeEvent.actionName === "delete") onDelete();
    },
  });

  function renderWith(event: LogEventDTO, props: Record<string, unknown>) {
    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(
        <ThemeProvider override="light">
          <EntryRow event={event} {...props} />
        </ThemeProvider>,
      );
    });
    return tree!;
  }

  it("exposes Delete on the tappable needs-a-detail row", () => {
    const onDelete = jest.fn();
    const tree = renderWith(baseEvent({ status: "needs_clarification" }), {
      onPress: jest.fn(),
      ...deleteA11y(onDelete),
    });

    const node = tree.root.find(
      (n) =>
        Array.isArray(n.props.accessibilityActions) &&
        n.props.accessibilityActions.some(
          (a: { name: string }) => a.name === "delete",
        ) &&
        typeof n.props.onAccessibilityAction === "function",
    );
    act(() =>
      node.props.onAccessibilityAction({ nativeEvent: { actionName: "delete" } }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("exposes Delete on the failed row's Retry control", () => {
    const onDelete = jest.fn();
    const tree = renderWith(baseEvent({ status: "failed" }), {
      onRetry: jest.fn(),
      onEditAsText: jest.fn(),
      ...deleteA11y(onDelete),
    });

    const retry = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Retry" &&
        Array.isArray(n.props.accessibilityActions),
    );
    expect(
      retry.props.accessibilityActions.some(
        (a: { name: string }) => a.name === "delete",
      ),
    ).toBe(true);
    act(() =>
      retry.props.onAccessibilityAction({ nativeEvent: { actionName: "delete" } }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("exposes Delete on the plain completed-with-no-items row as one accessible element", () => {
    // A completed entry that produced nothing to show still renders a
    // server-backed row the user may want gone; with the delete props supplied
    // the row groups into a single accessible element carrying the action.
    const onDelete = jest.fn();
    const tree = renderWith(baseEvent({ status: "completed" }), {
      ...deleteA11y(onDelete),
    });

    const node = tree.root.find(
      (n) =>
        n.props.accessible === true &&
        Array.isArray(n.props.accessibilityActions) &&
        typeof n.props.onAccessibilityAction === "function",
    );
    expect(node.props.accessibilityLabel).toContain("milk");
    act(() =>
      node.props.onAccessibilityAction({ nativeEvent: { actionName: "delete" } }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("renders the plain completed row unchanged when no delete props are supplied", () => {
    const tree = renderWith(baseEvent({ status: "completed" }), {});
    expect(
      tree.root.findAll((n) => Array.isArray(n.props.accessibilityActions)),
    ).toHaveLength(0);
  });
});
