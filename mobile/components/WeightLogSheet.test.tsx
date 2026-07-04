/**
 * Tests for the FTY-183 WeightLogSheet — a true small (fit-to-content) native
 * sheet whose numeric field auto-focuses on present, with a human-formatted date
 * title (never a raw ISO string), preserving the FTY-101 save + re-fetch flow.
 */

import {
  act,
  create as render,
  type ReactTestRenderer,
} from "react-test-renderer";

import { WeightLogSheet } from "./WeightLogSheet";
import { WeightApiError, type WeightEntryDTO } from "@/api/weightEntries";
import type { ApiSession } from "@/state/session";
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { ThemeProvider, lightPalette } from "@/theme";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

const TODAY = "2026-07-01";

function entry(overrides: Partial<WeightEntryDTO> = {}): WeightEntryDTO {
  return {
    id: "w1",
    user_id: "user-1",
    weight_kg: 70,
    effective_date: "2026-06-24",
    created_at: "2026-06-24T08:00:00Z",
    updated_at: "2026-06-24T08:00:00Z",
    ...overrides,
  };
}

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return trackReactTestRenderer(tree);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

/** The resolved `color` style of a rendered node (style is `[base, {color}]`). */
function styleColor(node: { props: { style?: unknown } }): string | undefined {
  const style = node.props.style;
  const arr = Array.isArray(style) ? style : [style];
  const withColor = arr.find(
    (s): s is { color: string } =>
      typeof s === "object" && s !== null && "color" in s,
  );
  return withColor?.color;
}

function weightInput(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) =>
      typeof n.props.accessibilityLabel === "string" &&
      (n.props.accessibilityLabel as string).startsWith("Weight in"),
  );
}

function defaultProps(
  overrides: Partial<React.ComponentProps<typeof WeightLogSheet>> = {},
) {
  return {
    visible: true,
    onClose: jest.fn(),
    onSaved: jest.fn(),
    session: SESSION,
    unitsPreference: "imperial" as const,
    lastEntry: null,
    today: TODAY,
    create: jest.fn().mockResolvedValue(entry()),
    ...overrides,
  };
}

describe("WeightLogSheet", () => {
  beforeEach(() => {
    mockReduceMotion(false);
  });

  afterEach(() => {
    cleanupReactTestRenderers();
    jest.restoreAllMocks();
  });

  it("renders nothing until presented (visible=false → no field mounted)", () => {
    const tree = mount(
      <WeightLogSheet {...defaultProps({ visible: false })} />,
    );
    const inputs = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Weight in"),
    );
    expect(inputs).toHaveLength(0);
  });

  it("auto-focuses the numeric field on present (keyboard up immediately)", () => {
    const tree = mount(<WeightLogSheet {...defaultProps()} />);
    expect(weightInput(tree).props.autoFocus).toBe(true);
  });

  it("renders a human-formatted date title, never a raw ISO string", () => {
    const tree = mount(<WeightLogSheet {...defaultProps()} />);
    const text = allText(tree);
    expect(text).toContain("Today");
    expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });

  it("seeds the field from the last entry in display units", () => {
    // 70 kg → ~154.3 lb for an imperial user.
    const tree = mount(
      <WeightLogSheet
        {...defaultProps({ lastEntry: entry({ weight_kg: 70 }) })}
      />,
    );
    expect(weightInput(tree).props.value).toBe("154.3");
  });

  it("saves via the create endpoint, then calls onSaved and onClose", async () => {
    const create = jest.fn().mockResolvedValue(entry());
    const onSaved = jest.fn();
    const onClose = jest.fn();
    const tree = mount(
      <WeightLogSheet {...defaultProps({ create, onSaved, onClose })} />,
    );

    act(() => weightInput(tree).props.onChangeText("155"));
    const submit = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Log weight" &&
        typeof n.props.onPress === "function",
    );
    await act(async () => {
      submit.props.onPress();
    });

    expect(create).toHaveBeenCalledWith(SESSION, 155, TODAY);
    expect(onSaved).toHaveBeenCalledWith(TODAY);
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the sheet open and shows a message when the save fails, never echoing the value", async () => {
    const create = jest
      .fn()
      .mockRejectedValue(
        new WeightApiError(
          422,
          "That weight couldn't be saved. Check it and try again.",
        ),
      );
    const onClose = jest.fn();
    const tree = mount(
      <WeightLogSheet {...defaultProps({ create, onClose })} />,
    );

    act(() => weightInput(tree).props.onChangeText("155"));
    const submit = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Log weight" &&
        typeof n.props.onPress === "function",
    );
    await act(async () => {
      submit.props.onPress();
    });

    expect(onClose).not.toHaveBeenCalled();
    const text = allText(tree);
    expect(text).toContain("couldn't be saved");
    expect(text).not.toContain("155");
  });

  it("exposes a visible, labeled Cancel control that dismisses the sheet", () => {
    const onClose = jest.fn();
    const tree = mount(<WeightLogSheet {...defaultProps({ onClose })} />);
    const cancel = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Cancel" &&
        n.props.accessibilityRole === "button" &&
        typeof n.props.onPress === "function",
    );
    // A 44pt minimum target keeps it reachable for touch and VoiceOver.
    expect(cancel.props.style.minHeight).toBeGreaterThanOrEqual(44);
    act(() => cancel.props.onPress());
    expect(onClose).toHaveBeenCalled();
  });

  it("renders the Cancel label in accentText, not accent (WCAG AA on the light surface)", () => {
    const tree = mount(<WeightLogSheet {...defaultProps()} />);
    const cancelLabel = tree.root.find(
      (n) => n.props.children === "Cancel" && typeof n.props.style !== "undefined",
    );
    expect(styleColor(cancelLabel)).toBe(lightPalette.accentText);
  });

  it("calls onClose when the native sheet is dismissed by gesture", () => {
    const onClose = jest.fn();
    const tree = mount(<WeightLogSheet {...defaultProps({ onClose })} />);
    const sheetScreen = tree.root.find(
      (n) => typeof n.props.onDismissed === "function",
    );
    act(() => {
      sheetScreen.props.onDismissed({ nativeEvent: { dismissCount: 1 } });
    });
    expect(onClose).toHaveBeenCalled();
  });
});
