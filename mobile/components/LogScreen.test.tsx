import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { AccessibilityInfo, Animated } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LogScreen } from "./LogScreen";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
import type { SavedFoodDTO } from "@/api/savedFoods";
import type { Session } from "@/state/session";

// LogScreen imports BarcodeScannerScreen which imports expo-camera native
// modules; mock those before any tests run.

let mockTriggerScan:
  | ((result: { data: string; type: string }) => void)
  | undefined;

jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    useCameraPermissions: jest.fn(() => [
      { status: "granted", granted: true, canAskAgain: false, expires: "never" },
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    ]),
    CameraView: jest.fn().mockImplementation(
      ({
        onBarcodeScanned,
      }: {
        onBarcodeScanned?: (r: { data: string; type: string }) => void;
      }) => {
        mockTriggerScan = onBarcodeScanned;
        return ReactLib.createElement(ReactNative.View, {
          testID: "camera-view",
        });
      },
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

const SESSION: Session = {
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

function event(overrides: Partial<LogEventDTO>): LogEventDTO {
  return {
    id: "id",
    user_id: SESSION!.userId,
    raw_text: "two eggs",
    status: "pending",
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
    ...overrides,
  };
}

function savedFood(overrides: Partial<SavedFoodDTO> = {}): SavedFoodDTO {
  return {
    id: "sf-1",
    user_id: SESSION!.userId,
    name: "Greek yogurt",
    calories: 200,
    protein_g: 22,
    carbs_g: 10,
    fat_g: 5,
    serving_size: 1,
    serving_unit: "cup",
    source: "saved_from_correction",
    created_at: "2026-06-28T10:00:00Z",
    updated_at: "2026-06-28T10:00:00Z",
    ...overrides,
  };
}

const INACTIVE = () => false;

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        {element}
      </SafeAreaProvider>,
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

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return (
    tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0
  );
}

function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

function inputValue(tree: ReactTestRenderer, label: string): string {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  return node.props.value as string;
}

// ─── Basic rendering ──────────────────────────────────────────────────────────

describe("LogScreen", () => {
  it("shows sign-in prompt when there is no session", () => {
    const tree = mount(
      <LogScreen session={null} useActive={INACTIVE} />,
    );
    expect(textContent(tree)).toContain("Sign in to log food");
  });

  it("renders the natural-language composer with accessible label", () => {
    const tree = mount(
      <LogScreen session={SESSION} useActive={INACTIVE} />,
    );
    expect(hasA11yLabel(tree, "Log food or exercise")).toBe(true);
  });
});

// ─── Submit → stay-on-page ────────────────────────────────────────────────────

describe("LogScreen submit — stay-on-page", () => {
  it("keeps the composer mounted and adds the entry to the feed on submit", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "server-1", raw_text: "apple", status: "pending" }),
    );
    const tree = mount(
      <LogScreen
        session={SESSION}
        create={create}
        useActive={INACTIVE}
      />,
    );

    typeInto(tree, "Log food or exercise", "apple");
    press(tree, "Add entry");

    // Entry appears immediately as pending (skeleton placeholder).
    await act(async () => {});

    // Composer is still present (page did not navigate away).
    expect(hasA11yLabel(tree, "Log food or exercise")).toBe(true);
    // Entry appears in the feed with "estimating" accessible state.
    expect(hasA11yLabel(tree, "apple, estimating")).toBe(true);
    // create was called with the trimmed text.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "apple",
    );
  });

  it("clears the input immediately on submit before the API resolves", async () => {
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "banana");
    press(tree, "Add entry");

    // The field is empty before the create resolves.
    expect(inputValue(tree, "Log food or exercise")).toBe("");

    // Entry is pending in the feed.
    expect(hasA11yLabel(tree, "banana, estimating")).toBe(true);

    await act(async () => {
      resolveCreate(event({ id: "s1", raw_text: "banana", status: "pending" }));
    });
  });
});

// ─── Field clear + rapid successive adds ─────────────────────────────────────

describe("LogScreen field clear + rapid adds", () => {
  it("two sequential submits both appear in the feed", async () => {
    const create = jest
      .fn()
      .mockResolvedValueOnce(
        event({ id: "s1", raw_text: "apple", status: "pending" }),
      )
      .mockResolvedValueOnce(
        event({ id: "s2", raw_text: "banana", status: "pending" }),
      );

    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "apple");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Field is empty after first submit.
    expect(inputValue(tree, "Log food or exercise")).toBe("");
    expect(hasA11yLabel(tree, "apple, estimating")).toBe(true);

    typeInto(tree, "Log food or exercise", "banana");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Both entries are in the feed.
    expect(hasA11yLabel(tree, "apple, estimating")).toBe(true);
    expect(hasA11yLabel(tree, "banana, estimating")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("");
  });
});

// ─── Added feed accumulation ──────────────────────────────────────────────────

describe("LogScreen added feed accumulation", () => {
  beforeEach(() => {
    mockTriggerScan = undefined;
  });

  it("typed, saved-food-applied, and barcode entries all land in the feed", async () => {
    jest.useFakeTimers();
    try {
      const yogurt = savedFood();
      const searchSavedFoods = jest
        .fn()
        .mockResolvedValue({ items: [yogurt], limit: 20 });
      const create = jest
        .fn()
        .mockResolvedValue(event({ id: "s1", raw_text: "apple", status: "pending" }));

      const tree = mount(
        <LogScreen
          session={SESSION}
          create={create}
          searchSavedFoods={searchSavedFoods}
          useActive={INACTIVE}
        />,
      );

      // 1. Typed entry.
      typeInto(tree, "Log food or exercise", "apple");
      await act(async () => {
        press(tree, "Add entry");
      });
      expect(hasA11yLabel(tree, "apple, estimating")).toBe(true);

      // 2. Saved-food entry: select suggestion then submit.
      create.mockResolvedValue(
        event({ id: "s2", raw_text: "Greek yogurt", status: "pending" }),
      );
      typeInto(tree, "Log food or exercise", "greek");
      await act(async () => {
        jest.advanceTimersByTime(400);
      });
      press(tree, "Use saved food: Greek yogurt");
      await act(async () => {
        press(tree, "Add entry");
      });
      // Saved-food entry shows nutrition immediately (no skeleton).
      expect(hasA11yLabel(tree, "Greek yogurt, 200 kcal, Logged")).toBe(true);

      // 3. Barcode entry.
      create.mockResolvedValue(
        event({ id: "s3", raw_text: "5901234123457", status: "pending" }),
      );
      press(tree, "Scan barcode");
      await act(async () => {
        mockTriggerScan?.({ data: "5901234123457", type: "ean13" });
      });

      // All three entries are in the feed.
      expect(hasA11yLabel(tree, "apple, estimating")).toBe(true);
      expect(hasA11yLabel(tree, "Greek yogurt, 200 kcal, Logged")).toBe(true);
      expect(hasA11yLabel(tree, "5901234123457, estimating")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("label-uploaded entry lands in the feed", async () => {
    const uploadedEvent: LogEventDTO = {
      id: "label-1",
      user_id: SESSION!.userId,
      raw_text: "nutrition label",
      status: "pending",
      created_at: "2026-06-28T10:00:00Z",
      updated_at: "2026-06-28T10:00:00Z",
    };
    const uploadLabel = jest.fn().mockResolvedValue(uploadedEvent);
    const labelTakePhoto = jest
      .fn()
      .mockResolvedValue({ uri: "file:///label.jpg" });

    const tree = mount(
      <LogScreen
        session={SESSION}
        useActive={INACTIVE}
        uploadLabel={uploadLabel}
        labelTakePhoto={labelTakePhoto}
      />,
    );

    press(tree, "Capture label");
    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });

    expect(hasA11yLabel(tree, "nutrition label, estimating")).toBe(true);
  });
});

// ─── Typeahead reuse ──────────────────────────────────────────────────────────

describe("LogScreen typeahead reuse", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("queries saved foods reactively as the user types (after debounce)", async () => {
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [savedFood()], limit: 20 });

    const tree = mount(
      <LogScreen
        session={SESSION}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );

    typeInto(tree, "Log food or exercise", "greek");

    // No search before the debounce window.
    expect(searchSavedFoods).not.toHaveBeenCalled();

    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    // Backend called with the raw query — no extra client-side filtering.
    expect(searchSavedFoods).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek",
    );
  });

  it("applies the saved food's stored nutrition (estimator bypassed) on selection + submit", async () => {
    const yogurt = savedFood({ calories: 200 });
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [yogurt], limit: 20 });
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "Greek yogurt", status: "pending" }),
    );

    const tree = mount(
      <LogScreen
        session={SESSION}
        create={create}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );

    typeInto(tree, "Log food or exercise", "greek");
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    press(tree, "Use saved food: Greek yogurt");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Saved food calories visible immediately — no skeleton, no polling wait.
    expect(hasA11yLabel(tree, "Greek yogurt, 200 kcal, Logged")).toBe(true);

    // Log event was still created for persistence.
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("leaves the estimator path for a non-suggestion submit", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "oatmeal", status: "pending" }),
    );
    const tree = mount(
      <LogScreen
        session={SESSION}
        create={create}
        useActive={INACTIVE}
      />,
    );

    typeInto(tree, "Log food or exercise", "oatmeal");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Normal entry: shows skeleton (estimating) since no saved food was applied.
    expect(hasA11yLabel(tree, "oatmeal, estimating")).toBe(true);
  });
});

// ─── In-place skeleton → value, no layout shift ───────────────────────────────

describe("LogScreen in-place skeleton → value, no layout shift", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest
      .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
      .mockResolvedValue(false);
    jest
      .spyOn(AccessibilityInfo, "addEventListener")
      .mockReturnValue({ remove: jest.fn() } as never);
  });
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("pending feed row renders a skeleton placeholder (progressbar role)", async () => {
    const create = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "eggs");
    press(tree, "Add entry");

    // Accessible label indicates "estimating".
    expect(hasA11yLabel(tree, "eggs, estimating")).toBe(true);
    // Skeleton progressbar is rendered.
    const progressbars = tree.root.findAll(
      (n) => n.props.accessibilityRole === "progressbar",
    );
    expect(progressbars.length).toBeGreaterThan(0);
  });

  it("feed row container has a stable fixed height throughout the transition", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "eggs", status: "pending" }),
    );
    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "eggs");
    press(tree, "Add entry");
    await act(async () => {});

    // Find all nodes that have 'eggs, estimating' as accessibilityLabel.
    const feedRowNodes = tree.root.findAll(
      (n) => n.props.accessibilityLabel === "eggs, estimating",
    );
    expect(feedRowNodes.length).toBeGreaterThan(0);

    const rowNode = feedRowNodes[0];
    const styles: Record<string, unknown>[] = Array.isArray(rowNode.props.style)
      ? rowNode.props.style
      : [rowNode.props.style];
    const combined = Object.assign({}, ...styles);
    // Row has a fixed height so the layout footprint is stable.
    expect(typeof combined.height).toBe("number");
  });

  it("resolved values appear in the same slot once polled to terminal", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "eggs", status: "pending" }),
    );
    const poll = jest
      .fn()
      .mockResolvedValue([
        event({ id: "s1", raw_text: "eggs", status: "completed" }),
      ]);

    const tree = mount(
      <LogScreen
        session={SESSION}
        create={create}
        poll={poll}
        useActive={() => true}
        pollIntervalMs={500}
      />,
    );

    typeInto(tree, "Log food or exercise", "eggs");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Pending: skeleton + estimating label.
    expect(hasA11yLabel(tree, "eggs, estimating")).toBe(true);

    // Advance time to trigger one poll tick.
    act(() => jest.advanceTimersByTime(500));
    await act(async () => {});

    // Resolved: row now shows "logged" accessible state.
    expect(hasA11yLabel(tree, "eggs, Logged")).toBe(true);
    // Skeleton placeholder gone.
    expect(hasA11yLabel(tree, "eggs, estimating")).toBe(false);
  });

  it("Reduce Motion: uses plain timing fade (not spring) for the reveal", async () => {
    jest
      .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
      .mockResolvedValue(true);

    const timingSpy = jest
      .spyOn(Animated, "timing")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);

    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "toast", status: "completed" }),
    );

    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "toast");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Let the isReduceMotionEnabled promise resolve inside the FeedRowResolved effect.
    await act(async () => {});

    // Animated.timing (not spring) should have been called for the fade-in.
    expect(timingSpy).toHaveBeenCalled();
  });

  it("normal motion: uses spring for the content reveal", async () => {
    jest
      .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
      .mockResolvedValue(false);

    const springSpy = jest
      .spyOn(Animated, "spring")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);

    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "toast", status: "completed" }),
    );

    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "toast");
    await act(async () => {
      press(tree, "Add entry");
    });

    await act(async () => {});

    expect(springSpy).toHaveBeenCalled();
  });
});

// ─── Accessibility ────────────────────────────────────────────────────────────

describe("LogScreen accessibility", () => {
  it("exposes accessible VoiceOver labels on both capture affordances", () => {
    const tree = mount(
      <LogScreen session={SESSION} useActive={INACTIVE} />,
    );
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(true);
    expect(hasA11yLabel(tree, "Capture label")).toBe(true);
  });

  it("feed row exposes resolving state while pending", async () => {
    const create = jest.fn().mockReturnValue(new Promise(() => {}));
    const tree = mount(
      <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
    );

    typeInto(tree, "Log food or exercise", "oatmeal");
    press(tree, "Add entry");

    // Pending row accessible label conveys "estimating".
    expect(hasA11yLabel(tree, "oatmeal, estimating")).toBe(true);
  });

  it("feed row exposes resolved state once terminal status is reached", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "oatmeal", status: "completed" }),
    );
    const poll = jest
      .fn()
      .mockResolvedValue([
        event({ id: "s1", raw_text: "oatmeal", status: "completed" }),
      ]);

    jest.useFakeTimers();
    try {
      const tree = mount(
        <LogScreen
          session={SESSION}
          create={create}
          poll={poll}
          useActive={() => true}
          pollIntervalMs={300}
        />,
      );

      typeInto(tree, "Log food or exercise", "oatmeal");
      await act(async () => {
        press(tree, "Add entry");
      });

      act(() => jest.advanceTimersByTime(300));
      await act(async () => {});

      // Resolved row label contains "logged".
      expect(hasA11yLabel(tree, "oatmeal, Logged")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("feed row reflects a failed terminal status (never reads as logged/estimating)", async () => {
    const create = jest.fn().mockResolvedValue(
      event({ id: "s1", raw_text: "mystery stew", status: "pending" }),
    );
    const poll = jest
      .fn()
      .mockResolvedValue([
        event({ id: "s1", raw_text: "mystery stew", status: "failed" }),
      ]);

    jest.useFakeTimers();
    try {
      const tree = mount(
        <LogScreen
          session={SESSION}
          create={create}
          poll={poll}
          useActive={() => true}
          pollIntervalMs={300}
        />,
      );

      typeInto(tree, "Log food or exercise", "mystery stew");
      await act(async () => {
        press(tree, "Add entry");
      });

      act(() => jest.advanceTimersByTime(300));
      await act(async () => {});

      // Failed status surfaces its own copy — not "logged" or "estimating".
      expect(hasA11yLabel(tree, "mystery stew, Estimate didn't finish")).toBe(
        true,
      );
      expect(hasA11yLabel(tree, "mystery stew, Logged")).toBe(false);
      expect(hasA11yLabel(tree, "mystery stew, estimating")).toBe(false);
      // Visible status copy reflects the failure, not a stuck "Estimating…".
      expect(textContent(tree)).toContain("Couldn't estimate");
      expect(textContent(tree)).not.toContain("Estimating");
    } finally {
      jest.useRealTimers();
    }
  });

  it("saved-food row immediately exposes resolved accessible state", async () => {
    jest.useFakeTimers();
    try {
      const yogurt = savedFood({ name: "Protein bar", calories: 250 });
      const searchSavedFoods = jest
        .fn()
        .mockResolvedValue({ items: [yogurt], limit: 20 });
      const create = jest.fn().mockResolvedValue(
        event({ id: "s1", raw_text: "Protein bar", status: "pending" }),
      );

      const tree = mount(
        <LogScreen
          session={SESSION}
          create={create}
          searchSavedFoods={searchSavedFoods}
          useActive={INACTIVE}
        />,
      );

      typeInto(tree, "Log food or exercise", "protein");
      await act(async () => {
        jest.advanceTimersByTime(400);
      });
      press(tree, "Use saved food: Protein bar");
      await act(async () => {
        press(tree, "Add entry");
      });

      // No skeleton: saved food resolved immediately.
      expect(hasA11yLabel(tree, "Protein bar, 250 kcal, Logged")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});

// ─── Error handling ───────────────────────────────────────────────────────────

describe("LogScreen error handling", () => {
  it("rolls back and shows error when submit fails", async () => {
    jest.useFakeTimers();
    try {
      const create = jest
        .fn()
        .mockRejectedValue(
          new LogEventApiError(422, "That entry couldn't be saved."),
        );
      const tree = mount(
        <LogScreen session={SESSION} create={create} useActive={INACTIVE} />,
      );

      typeInto(tree, "Log food or exercise", "blernsday");
      await act(async () => {
        press(tree, "Add entry");
      });

      // Error surfaced; optimistic entry rolled back; composer restored.
      expect(textContent(tree)).toContain("That entry couldn't be saved.");
      expect(inputValue(tree, "Log food or exercise")).toBe("blernsday");
      expect(hasA11yLabel(tree, "blernsday, estimating")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });
});
