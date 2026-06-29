/**
 * Tests for the connect-to-your-server screen (FTY-107).
 *
 * Covers the five review-focus concerns at the UI boundary:
 * - URL validation (typed + scanned): malformed / non-http(s) / empty rejected
 *   inline before any network call.
 * - Reachability: /healthz OK → persists + advances; failure → "Can't reach
 *   {host}" with Retry, URL stays editable, retry re-probes.
 * - Persistence + accessor: a connected URL is persisted (normalized) to the
 *   injected store, never logged as a secret.
 * - QR scan: a valid-URL QR fills the field and does not auto-authenticate or
 *   persist anything.
 * - Accessibility + light/dark parity: labelled controls, ≥44pt targets, both
 *   palettes render.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PermissionStatus, type PermissionResponse } from "expo";

// config (imported transitively via the connection provider) reads expo-constants.
const mockExtra: { apiBaseUrl?: string } = {};
jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    get expoConfig() {
      return { extra: mockExtra };
    },
  },
}));

// Camera mock — exposes a trigger so a test can fire a simulated QR scan.
let mockTriggerScan: ((data: string) => void) | undefined;
jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  const MockCameraView = jest
    .fn()
    .mockImplementation(
      ({ onBarcodeScanned }: { onBarcodeScanned?: (r: unknown) => void }) => {
        mockTriggerScan = onBarcodeScanned
          ? (data: string) =>
              onBarcodeScanned({
                data,
                type: "qr",
                cornerPoints: [],
                bounds: { origin: { x: 0, y: 0 }, size: { width: 0, height: 0 } },
              })
          : undefined;
        return ReactLib.createElement(View, { testID: "camera-view" });
      },
    );
  return { CameraView: MockCameraView };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// eslint-disable-next-line import/first
import { ConnectScreen } from "./ConnectScreen";
// eslint-disable-next-line import/first
import { ConnectionProvider } from "@/state/connection";
// eslint-disable-next-line import/first
import { setConnectedBaseUrl } from "@/api/config";
// eslint-disable-next-line import/first
import type { ServerConnectionStore } from "@/state/serverConnectionStore";
// eslint-disable-next-line import/first
import { ThemeProvider, lightPalette, darkPalette } from "@/theme";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fakeStore(initial: string | null = null) {
  let value = initial;
  return {
    load: jest.fn(async () => value),
    save: jest.fn(async (u: string) => {
      value = u;
    }),
    clear: jest.fn(async () => {
      value = null;
    }),
  } satisfies ServerConnectionStore;
}

function grantedPermission(): PermissionResponse {
  return {
    status: PermissionStatus.GRANTED,
    granted: true,
    canAskAgain: true,
    expires: "never",
  };
}
function grantedHook() {
  const perm = grantedPermission();
  const req = jest.fn(async () => perm);
  return () => [perm, req, req] as [typeof perm, typeof req, typeof req];
}

function reachableFetch() {
  return jest.fn(async () => ({
    ok: true,
    json: async () => ({ status: "ok" }),
  })) as unknown as jest.MockedFunction<typeof fetch>;
}
function unreachableFetch() {
  return jest.fn(async () => {
    throw new TypeError("Network request failed");
  }) as unknown as jest.MockedFunction<typeof fetch>;
}

type Scheme = "light" | "dark";

async function mount(opts: {
  onConnected?: (url: string) => void;
  fetchImpl?: typeof fetch;
  store?: ServerConnectionStore;
  scheme?: Scheme;
}): Promise<ReactTestRenderer> {
  const store = opts.store ?? fakeStore(null);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        <ThemeProvider override={opts.scheme ?? "light"}>
          <ConnectionProvider store={store}>
            <ConnectScreen
              onConnected={opts.onConnected ?? (() => {})}
              {...(opts.fetchImpl ? { fetchImpl: opts.fetchImpl } : {})}
              permissionsHook={grantedHook()}
            />
          </ConnectionProvider>
        </ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function input(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) => n.props.accessibilityLabel === "Server address",
  );
}
function inputValue(tree: ReactTestRenderer): string {
  return input(tree).props.value as string;
}
function setText(tree: ReactTestRenderer, text: string): void {
  act(() => {
    (input(tree).props.onChangeText as (t: string) => void)(text);
  });
}
function buttonNode(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
}
async function press(tree: ReactTestRenderer, label: string): Promise<void> {
  await act(async () => {
    (buttonNode(tree, label).props.onPress as () => void)();
    // let the async validate → probe → connect → onConnected chain settle
    await new Promise((r) => setTimeout(r, 0));
  });
}
function buttonLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.onPress === "function" && !!n.props.accessibilityLabel)
    .map((n) => n.props.accessibilityLabel as string);
}
function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return style.reduce<Record<string, unknown>>(
      (acc, s) => ({ ...acc, ...flattenStyle(s) }),
      {},
    );
  }
  return (style as Record<string, unknown>) ?? {};
}

afterEach(() => {
  setConnectedBaseUrl(null);
  mockTriggerScan = undefined;
});

// ─── URL validation (typed) ──────────────────────────────────────────────────

describe("URL validation before any network call", () => {
  it("rejects empty input with an inline error and never probes", async () => {
    const fetchImpl = reachableFetch();
    const tree = await mount({ fetchImpl });
    await press(tree, "Connect");
    const text = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(text).toContain("Enter your server's address.");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a non-http(s) scheme inline and never probes", async () => {
    const fetchImpl = reachableFetch();
    const tree = await mount({ fetchImpl });
    setText(tree, "javascript:alert(1)");
    await press(tree, "Connect");
    const text = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(text).toContain("Use an http:// or https:// address.");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a malformed string inline and never probes", async () => {
    const fetchImpl = reachableFetch();
    const tree = await mount({ fetchImpl });
    setText(tree, "not a url");
    await press(tree, "Connect");
    const text = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(text).toContain("That doesn't look like a valid server address.");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

// ─── Reachability + persistence ──────────────────────────────────────────────

describe("reachability + persistence", () => {
  it("probes /healthz, persists the normalized URL, and advances on success", async () => {
    const fetchImpl = reachableFetch();
    const store = fakeStore(null);
    const onConnected = jest.fn();
    const tree = await mount({ fetchImpl, store, onConnected });

    setText(tree, "https://my-server.example.com/");
    await press(tree, "Connect");

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://my-server.example.com/healthz",
      expect.objectContaining({ method: "GET" }),
    );
    expect(store.save).toHaveBeenCalledWith("https://my-server.example.com");
    expect(onConnected).toHaveBeenCalledWith("https://my-server.example.com");
  });

  it("shows 'Can't reach {host}' with Retry, keeps the URL editable, and does not persist", async () => {
    const fetchImpl = unreachableFetch();
    const store = fakeStore(null);
    const onConnected = jest.fn();
    const tree = await mount({ fetchImpl, store, onConnected });

    setText(tree, "https://down.example.com");
    await press(tree, "Connect");

    const text = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(text).toContain("Can't reach down.example.com");
    // Retry affordance present; URL stays editable and unchanged.
    expect(buttonLabels(tree)).toContain("Retry");
    expect(inputValue(tree)).toBe("https://down.example.com");
    expect(store.save).not.toHaveBeenCalled();
    expect(onConnected).not.toHaveBeenCalled();
  });

  it("retry re-probes and connects once the server is reachable", async () => {
    // Fail first, succeed on retry.
    let online = false;
    const fetchImpl = jest.fn(async () => {
      if (!online) throw new TypeError("down");
      return { ok: true, json: async () => ({ status: "ok" }) };
    }) as unknown as typeof fetch;
    const store = fakeStore(null);
    const onConnected = jest.fn();
    const tree = await mount({ fetchImpl, store, onConnected });

    setText(tree, "https://my-server.example.com");
    await press(tree, "Connect");
    expect(onConnected).not.toHaveBeenCalled();

    online = true;
    await press(tree, "Retry");
    expect(store.save).toHaveBeenCalledWith("https://my-server.example.com");
    expect(onConnected).toHaveBeenCalledWith("https://my-server.example.com");
  });

  it("does not log the server URL as a secret while connecting", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      const tree = await mount({ fetchImpl: reachableFetch() });
      setText(tree, "https://secret-host.example.com");
      await press(tree, "Connect");
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(call.map((c) => String(c)).join(" ")).not.toContain(
            "secret-host.example.com",
          );
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});

// ─── QR scan ─────────────────────────────────────────────────────────────────

describe("QR scan", () => {
  it("fills the URL field from a valid-URL QR without authenticating or persisting", async () => {
    const fetchImpl = reachableFetch();
    const store = fakeStore(null);
    const onConnected = jest.fn();
    const tree = await mount({ fetchImpl, store, onConnected });

    // Open the scanner, then fire a simulated scan.
    await act(async () => {
      (buttonNode(tree, "Scan QR").props.onPress as () => void)();
    });
    expect(mockTriggerScan).toBeDefined();
    act(() => {
      mockTriggerScan?.("https://scanned.example.com/");
    });

    expect(inputValue(tree)).toBe("https://scanned.example.com");
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(store.save).not.toHaveBeenCalled();
    expect(onConnected).not.toHaveBeenCalled();
  });

  it("rejects a QR whose payload is not a valid server URL with a gentle message", async () => {
    const tree = await mount({ fetchImpl: reachableFetch() });
    await act(async () => {
      (buttonNode(tree, "Scan QR").props.onPress as () => void)();
    });
    act(() => {
      mockTriggerScan?.("javascript:alert(1)");
    });
    const text = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    expect(text).toContain("That QR isn't a Fatty server URL.");
    expect(inputValue(tree)).toBe("");
  });
});

// ─── Accessibility + light/dark parity ───────────────────────────────────────

describe("accessibility + light/dark parity", () => {
  it("labels the URL field, Connect, and Scan controls", async () => {
    const tree = await mount({});
    const labels = tree.root
      .findAll((n) => !!n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);
    expect(labels).toEqual(
      expect.arrayContaining(["Server address", "Connect", "Scan QR"]),
    );
  });

  it("gives the primary action a ≥44pt tap target", async () => {
    const tree = await mount({});
    const style = flattenStyle(buttonNode(tree, "Connect").props.style);
    expect(style.minHeight).toBe(44);
  });

  it("marks the inline error as an alert for assistive tech", async () => {
    const tree = await mount({ fetchImpl: reachableFetch() });
    await press(tree, "Connect");
    const alert = tree.root.find(
      (n) =>
        n.props.accessibilityRole === "alert" &&
        n.props.children === "Enter your server's address.",
    );
    expect(alert).toBeTruthy();
  });

  it("renders the URL field with the light then dark text colour", async () => {
    const light = await mount({ scheme: "light" });
    expect(flattenStyle(input(light).props.style).color).toBe(lightPalette.text);

    const dark = await mount({ scheme: "dark" });
    expect(flattenStyle(input(dark).props.style).color).toBe(darkPalette.text);
  });
});
