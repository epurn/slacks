import React from "react";
import { act, create } from "react-test-renderer";

import { OfflineEntryRow } from "./OfflineEntryRow";
import type { OutboxSyncState } from "@/state/outbox";

// OfflineEntryRow renders its status glyph through AppIcon (expo-symbols) so the
// indicator comes from the app's single SF-Symbol set, never a raw Unicode/emoji
// character used as chrome. Stub the native SymbolView and expose the requested
// symbol name via testID so tests can assert which glyph was used.
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({ name }: { name: string }) =>
      ReactLib.createElement(View, { testID: `sf-symbol-${String(name)}` }),
  };
});

function renderRow(state: OutboxSyncState) {
  let tree: ReturnType<typeof create>;
  act(() => {
    tree = create(<OfflineEntryRow rawText="two eggs" state={state} />);
  });
  return tree!;
}

describe("OfflineEntryRow", () => {
  it.each<[OutboxSyncState, string]>([
    ["submitting", "arrow.triangle.2.circlepath"],
    ["failed", "exclamationmark.circle"],
    ["queued", "arrow.up.circle"],
    ["accepted", "arrow.up.circle"],
  ])("renders the %s state through an SF Symbol, not a raw glyph", (state, symbol) => {
    const tree = renderRow(state);
    const icon = tree.root.find((n) => n.props.testID === `sf-symbol-${symbol}`);
    expect(icon).toBeTruthy();
  });

  it("carries the offline status in words on the accessible row", () => {
    const tree = renderRow("queued");
    const row = tree.root.find(
      (n) => n.props.accessibilityLabel === "two eggs, offline, queued to send",
    );
    expect(row).toBeTruthy();
  });
});
