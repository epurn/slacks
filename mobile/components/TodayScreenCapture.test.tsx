import { act, type ReactTestRenderer } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import {
  LogEventApiError,
  type LogEventDTO,
} from "@/api/logEvents";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { activateVisualReviewPreset } from "@/e2e/visualReview";
import { QUIET_MS } from "@/e2e/visualReview/VisualReviewSettleOverlay";
import { __deactivateVisualReview } from "@/e2e/visualReview/session";

import {
  CAPTURE_BARCODE_GRANTED_PRESET,
  CAPTURE_CONFIRM_PARSED_EVENT,
  CAPTURE_CONFIRM_PARSED_PRESET,
  CAPTURE_CONFIRM_PARSED_PROPOSAL,
  CAPTURE_LABEL_GUIDANCE_PRESET,
} from "./today/captureVisualReview";
import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  countPendingRows,
  emptyClarification,
  event,
  foodItem,
  hasA11yLabel,
  inputValue,
  mount,
  press,
  summary,
  textContent,
  typeInto,
} from "./today/todayTestUtils";

// The beat haptics are mocked so transitions can be asserted through the real
// screen without a native Taptic Engine, and so a resolve/save/target beat
// firing in these suites never reaches a real (unsupported) native call.
jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// Capture the most-recent onBarcodeScanned so scanner tests can trigger a scan.
// Must be prefixed with "mock" to be accessible inside jest.mock() factories.
let mockTriggerScan:
  | ((result: { data: string; type: string }) => void)
  | undefined;

jest.mock("expo-camera", () => {
  // Use require() inside the factory — jest.mock() factories run before imports
  // and cannot close over module-scope variables (except mock-prefixed ones).
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
      ({ onBarcodeScanned }: { onBarcodeScanned?: (r: { data: string; type: string }) => void }) => {
        mockTriggerScan = onBarcodeScanned;
        return ReactLib.createElement(ReactNative.View, { testID: "camera-view" });
      },
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// The item-forward by-date feed (FTY-198) is read from a real endpoint by
// default (FTY-180). Stub it to an empty day so tests that don't exercise item
// rows stay hermetic — no real fetch — while tests that do pass an explicit
// `loadEntries` prop that overrides this default.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));

afterEach(cleanupTrees);

describe("TodayScreen barcode scanning", () => {
  beforeEach(() => {
    mockTriggerScan = undefined;
  });

  it("exposes an accessible Scan barcode entry point", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(true);
  });

  it("shows the scanner modal when the scan entry point is pressed", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");
    // After pressing, the CameraView mock renders and captures onBarcodeScanned.
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
  });

  it("a successful barcode read submits via createLogEvent and appears as pending", async () => {
    const load = jest.fn().mockResolvedValue([]);
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");

    act(() => {
      mockTriggerScan?.({ data: "5901234123457", type: "ean13" });
    });

    // create is called with the barcode string (not an image URI or object)
    expect(create).toHaveBeenCalledTimes(1);
    const [, rawText] = create.mock.calls[0];
    expect(rawText).toBe("5901234123457");

    // Entry appears immediately as pending before create resolves — a skeleton
    // (FTY-180), not the scanned barcode text.
    expect(textContent(tree)).not.toContain("5901234123457");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    const pendingRowsBeforeReconcile = countPendingRows(tree, "Waiting to estimate");

    // Reconcile with server response — still the same single pending row, no
    // duplicate spawned by the swap.
    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "5901234123457", status: "pending" }),
      );
    });
    expect(countPendingRows(tree, "Waiting to estimate")).toBe(
      pendingRowsBeforeReconcile,
    );
  });

  it("rolls back and surfaces an error when the barcode submit fails", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest
      .fn()
      .mockRejectedValue(
        new LogEventApiError(422, "That entry couldn't be saved."),
      );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");

    await act(async () => {
      mockTriggerScan?.({ data: "5901234123457", type: "ean13" });
    });

    // Optimistic entry rolled back; error surfaced.
    expect(textContent(tree)).toContain("That entry couldn't be saved.");
    expect(textContent(tree)).toContain("Log your first thing");
  });

  it("'Type it instead' dismisses the scanner and lands in a pre-filled, focused composer (never a dead end)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);

    // The scanner lives in a full-screen Modal; grab its dismissal hook while it
    // is open so we can drive the "dismissal committed" moment deterministically.
    const scannerModalOnDismiss = tree.root.find(
      (n) => typeof n.props.onDismiss === "function",
    ).props.onDismiss as () => void;

    // Spy on the composer TextInput instance's imperative `focus()` right before
    // the fallback so we measure only the focus the fallback drives — the
    // never-a-dead-end wiring (FTY-194) raises the keyboard in place.
    const composer = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Log food or exercise" &&
        typeof n.props.onChangeText === "function",
    );
    // jest-expo's TextInput `focus` mock is shared across the suite, so clear it
    // to measure only the focus this fallback drives.
    const focusSpy = jest.spyOn(
      composer.instance as { focus: () => void },
      "focus",
    );
    focusSpy.mockClear();

    press(tree, "Type it instead");

    // The scanner is dismissed and the composer is pre-filled immediately with an
    // editable packaged-food starter — the barcode surface never dead-ends into a
    // feed with only "close", and it never drops the user into a blank field
    // (design §3: "Barcode not found → NL composer (pre-filled)").
    expect(hasA11yLabel(tree, "Close scanner")).toBe(false);
    expect(inputValue(tree, "Log food or exercise")).toBe("1 serving of ");

    // Focus is NOT raised synchronously — the full-screen scanner Modal still
    // owns the responder while it slides out, so an early focus would be
    // swallowed and the keyboard would never rise.
    expect(focusSpy).not.toHaveBeenCalled();

    // Once the Modal's dismissal has committed (iOS fires `onDismiss` only after
    // the slide-out finishes), the composer takes focus — the fallback genuinely
    // lands in a *focused* composer, not just a pre-filled one.
    act(() => {
      scannerModalOnDismiss();
    });
    expect(focusSpy).toHaveBeenCalled();
  });

  it("'Type it instead' keeps text the user already typed instead of clobbering it", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // The user typed a partial entry before reaching for the scanner.
    typeInto(tree, "Log food or exercise", "greek yogurt");

    press(tree, "Scan barcode");
    press(tree, "Type it instead");

    // Their in-progress text is preserved — only an empty composer is seeded.
    expect(inputValue(tree, "Log food or exercise")).toBe("greek yogurt");
  });
});

describe("TodayScreen label capture", () => {
  it("exposes an accessible Capture label entry point", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Capture label")).toBe(true);
  });

  it("shows the label capture modal when the label entry point is pressed", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    press(tree, "Capture label");

    // After pressing, the CameraCapture scaffold renders (permission granted by the mock).
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
  });

  it("adds the uploaded label event to the timeline via FTY-032 polling", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const createdEvent: LogEventDTO = {
      id: "label-server-1",
      user_id: SESSION!.userId,
      raw_text: "nutrition label photo",
      status: "pending",
      created_at: "2026-06-27T10:00:00Z",
      updated_at: "2026-06-27T10:00:00Z",
    };
    // The upload function returns the created pending event.
    const uploadLabel = jest.fn().mockResolvedValue(createdEvent);
    // The takePhoto mock skips the real camera ref.
    const labelTakePhoto = jest.fn().mockResolvedValue({ uri: "file:///label.jpg" });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={INACTIVE}
        uploadLabel={uploadLabel}
        labelTakePhoto={labelTakePhoto}
      />,
    );
    await act(async () => {});

    // Open label capture modal.
    press(tree, "Capture label");

    // Take photo.
    await act(async () => {
      press(tree, "Take photo");
    });

    // Upload.
    await act(async () => {
      press(tree, "Upload label");
    });

    // The uploaded event appears on the timeline as pending — a skeleton
    // (FTY-180), not the event's raw text.
    expect(textContent(tree)).not.toContain("nutrition label photo");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });
});

describe("TodayScreen confirm-parsed-values sheet", () => {
  const completedLabelEvent: LogEventDTO = {
    id: "label-event-1",
    user_id: SESSION!.userId,
    raw_text: "Nutrition label photo",
    status: "completed",
    created_at: "2026-07-02T10:00:00Z",
    updated_at: "2026-07-02T10:00:00Z",
  };

  function labelProposalItem(
    overrides: Partial<DerivedFoodItemDTO> = {},
  ): DerivedFoodItemDTO {
    return foodItem({
      id: "label-food-1",
      log_event_id: "label-event-1",
      name: "Granola bar",
      unit: "bar",
      status: "proposed",
      calories: 190,
      protein_g: 4,
      carbs_g: 29,
      fat_g: 7,
      source: { source_type: "user_label", label: "Label scan", ref: "user_label" },
      ...overrides,
    });
  }

  async function uploadLabel(tree: ReactTestRenderer): Promise<void> {
    press(tree, "Capture label");
    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });
    // Let the proposal read resolve and open the confirm sheet.
    await act(async () => {});
  }

  function labelProps(overrides: Record<string, unknown>) {
    return {
      session: SESSION,
      load: jest.fn().mockResolvedValue([]),
      useActive: INACTIVE,
      uploadLabel: jest.fn().mockResolvedValue(completedLabelEvent),
      labelTakePhoto: jest.fn().mockResolvedValue({ uri: "file:///label.jpg" }),
      ...overrides,
    };
  }

  it("shows the parsed values + Label scan provenance, not yet counted, after a legible upload", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const tree = mount(<TodayScreen {...labelProps({ getLabelProposal })} />);
    await act(async () => {});

    await uploadLabel(tree);

    // The proposal read was made for the uploaded event.
    expect(getLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
    );
    // The confirm sheet shows the parse, provenance, and the not-yet-counted state.
    const text = textContent(tree);
    expect(text).toContain("Granola bar");
    expect(text).toContain("190 kcal");
    expect(text).toContain("Label scan");
    expect(text).toContain("Not yet counted");
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(true);
  });

  it("confirm commits the parse and refreshes the day's totals in place", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest
      .fn()
      .mockResolvedValue(labelProposalItem({ status: "resolved" }));
    // First summary load excludes the proposal; after confirm it counts.
    const getDailySummary = jest
      .fn()
      .mockResolvedValueOnce(summary({ intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 }, has_intake: false }))
      .mockResolvedValue(summary({ intake: { calories: 190, protein_g: 4, carbs_g: 29, fat_g: 7 } }));

    const tree = mount(
      <TodayScreen
        {...labelProps({ getLabelProposal, confirmLabelProposal, getDailySummary })}
      />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    await act(async () => {
      press(tree, "Looks right, add it");
    });

    // Confirm called with an empty (unchanged) body; summary refetched.
    expect(confirmLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
      {},
    );
    // The entry now counts: the resolved item row shows the kcal (no "not counted").
    expect(hasA11yLabel(tree, "Granola bar, 190 kcal")).toBe(true);
    // Sheet dismissed — the confirm affordance is gone (in-place, no navigation).
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
  });

  it("adjusting a value sends the corrected number to the confirm action", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest
      .fn()
      .mockResolvedValue(labelProposalItem({ status: "resolved", calories: 250 }));
    const tree = mount(
      <TodayScreen {...labelProps({ getLabelProposal, confirmLabelProposal })} />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    press(tree, "Adjust values");
    typeInto(tree, "Calories value", "250");
    await act(async () => {
      press(tree, "Add adjusted values");
    });

    expect(confirmLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
      { calories: 250 },
    );
  });

  it("never silently counts: dismissing leaves an uncounted proposal, re-openable", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest.fn();
    const tree = mount(
      <TodayScreen {...labelProps({ getLabelProposal, confirmLabelProposal })} />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    // Dismiss without confirming.
    press(tree, "Close");

    expect(confirmLabelProposal).not.toHaveBeenCalled();
    // The proposal is honestly surfaced in the timeline as "not yet counted".
    expect(
      tree.root.findAll(
        (n) => n.props.accessibilityLabel === "Granola bar, 190 kcal, not yet counted",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("leaves the unreadable path unchanged when there is no proposal", async () => {
    // A not-a-label / unreadable disposition yields a null proposal.
    const getLabelProposal = jest.fn().mockResolvedValue(null);
    const failedEvent: LogEventDTO = { ...completedLabelEvent, status: "failed" };
    const tree = mount(
      <TodayScreen
        {...labelProps({
          getLabelProposal,
          uploadLabel: jest.fn().mockResolvedValue(failedEvent),
        })}
      />,
    );
    await act(async () => {});

    await uploadLabel(tree);

    // No confirm sheet is presented for a null proposal.
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
  });
});

describe("TodayScreen visual-review capture seam (FTY-268)", () => {
  const gThis = globalThis as Record<string, unknown>;
  const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
  const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

  function setE2E(on: boolean): void {
    gThis["__DEV__"] = on;
    if (on) {
      process.env["EXPO_PUBLIC_SLACKS_E2E"] = "true";
    } else {
      delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
    }
  }

  async function settle(): Promise<void> {
    // Real timers: waits out the settle overlay's network-quiet window
    // (QUIET_MS) rather than juggling fake timers against TodayScreen's own
    // polling/outbox timers, which this suite doesn't otherwise touch.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, QUIET_MS + 50));
    });
  }

  afterEach(() => {
    act(() => {
      __deactivateVisualReview();
    });
    gThis["__DEV__"] = ORIGINAL_DEV;
    if (ORIGINAL_E2E_ENV === undefined) {
      delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
    } else {
      process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
    }
  });

  it("opens the barcode scanner via the initial-state seam — no 'Scan barcode' tap — and settles", async () => {
    setE2E(true);
    activateVisualReviewPreset(CAPTURE_BARCODE_GRANTED_PRESET, null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // Already open — the scanner was never pressed.
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
    expect(hasA11yLabel(tree, "Camera scanner active")).toBe(true);

    await settle();
    expect(
      hasA11yLabel(tree, `visual-review-settled:${CAPTURE_BARCODE_GRANTED_PRESET}`),
    ).toBe(true);
  });

  it("opens label capture on the framing guidance via the initial-state seam — no 'Capture label' tap — and settles", async () => {
    setE2E(true);
    activateVisualReviewPreset(CAPTURE_LABEL_GUIDANCE_PRESET, null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
    expect(
      hasA11yLabel(tree, "Fit the nutrition label inside the frame"),
    ).toBe(true);

    await settle();
    expect(
      hasA11yLabel(tree, `visual-review-settled:${CAPTURE_LABEL_GUIDANCE_PRESET}`),
    ).toBe(true);
  });

  it("opens the confirm-parsed-values sheet seeded through the real label-proposal read — no capture taps — and settles", async () => {
    setE2E(true);
    activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    const load = jest.fn().mockResolvedValue([]);
    const getLabelProposal = jest
      .fn()
      .mockResolvedValue(CAPTURE_CONFIRM_PARSED_PROPOSAL);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={INACTIVE}
        getLabelProposal={getLabelProposal}
      />,
    );
    await act(async () => {});

    // Driven through the same real proposal-read path a live upload takes.
    expect(getLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      CAPTURE_CONFIRM_PARSED_EVENT.id,
    );
    const text = textContent(tree);
    expect(text).toContain("Granola bar");
    expect(text).toContain("Not yet counted");
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(true);

    await settle();
    expect(
      hasA11yLabel(tree, `visual-review-settled:${CAPTURE_CONFIRM_PARSED_PRESET}`),
    ).toBe(true);
  });

  it("is inert outside E2E mode: an active preset opens no capture surface (release build path)", async () => {
    setE2E(false);
    activateVisualReviewPreset(CAPTURE_BARCODE_GRANTED_PRESET, null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // Default capture behaviour, unchanged: nothing opens on its own.
    expect(hasA11yLabel(tree, "Close scanner")).toBe(false);
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
  });

  it("is inert with no active preset: default capture behaviour is unchanged", async () => {
    setE2E(true);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Close scanner")).toBe(false);
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
  });
});
