/**
 * Tests for the sign-in / create-account screen (FTY-091).
 *
 * Covers the review-focus concerns at the UI boundary:
 * - Form validation (email shape, password 8–128) blocks submit and shows inline
 *   errors before any network call.
 * - Server-scoped auth: a valid submit calls the FTY-090 controller against the
 *   FTY-107-connected base URL; the screen shows which server it targets.
 * - Non-enumerating error surface: an unknown email and a wrong password (both
 *   `401`) show the identical inline message.
 * - `409` on create surfaces a "sign in instead" affordance and flips the mode;
 *   `422` shows a generic message; a network failure is retryable, not a dead-end.
 * - Post-auth routing: a successful sign-in / create routes onward.
 * - Accessibility + light/dark parity: labelled fields, secure-text password,
 *   labelled mode toggle + submit, ≥44pt targets; both palettes render.
 * - No password or token is written to logs.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

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

// The session provider's default store touches the keychain; keep it inert.
jest.mock("expo-secure-store", () => ({
  setItemAsync: async () => {},
  getItemAsync: async () => null,
  deleteItemAsync: async () => {},
}));

// eslint-disable-next-line import/first
import { SignInScreen } from "./SignInScreen";
// eslint-disable-next-line import/first
import { AuthApiError } from "@/api/auth";
// eslint-disable-next-line import/first
import { setConnectedBaseUrl } from "@/api/config";
// eslint-disable-next-line import/first
import { ConnectionProvider } from "@/state/connection";
// eslint-disable-next-line import/first
import type { ServerConnectionStore } from "@/state/serverConnectionStore";
// eslint-disable-next-line import/first
import {
  SessionProvider,
  type AuthClient,
  type SessionRecord,
} from "@/state/session";
// eslint-disable-next-line import/first
import type { SessionStore } from "@/state/sessionStore";
// eslint-disable-next-line import/first
import { ThemeProvider, lightPalette, darkPalette } from "@/theme";

const SERVER = "https://home.example.net";
const RECORD: SessionRecord = {
  serverUrl: SERVER,
  token: "header.signature",
  userId: "11111111-1111-1111-1111-111111111111",
};

// ─── Fakes ───────────────────────────────────────────────────────────────────

function connectionStore(initial: string | null = SERVER): ServerConnectionStore {
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

function sessionStore(): SessionStore {
  let value: SessionRecord | null = null;
  return {
    load: jest.fn(async () => value),
    save: jest.fn(async (s: SessionRecord) => {
      value = s;
    }),
    clear: jest.fn(async () => {
      value = null;
    }),
  } satisfies SessionStore;
}

/** A controllable auth client: resolves a record, or rejects with a status. */
function authClient(over: Partial<AuthClient> = {}): AuthClient {
  return {
    signIn: jest.fn(async (serverUrl: string) => ({ ...RECORD, serverUrl })),
    createAccount: jest.fn(async (serverUrl: string) => ({
      ...RECORD,
      serverUrl,
    })),
    ...over,
  } satisfies AuthClient;
}

function rejectWith(status: number): jest.Mock {
  return jest.fn(async () => {
    throw new AuthApiError(
      status,
      status === 401
        ? "That email or password didn't match. Check them and try again."
        : status === 409
          ? "An account already exists for this email. Try signing in instead."
          : "Enter a valid email and a password of at least 8 characters.",
    );
  });
}

// ─── Mount + query helpers ───────────────────────────────────────────────────

type Scheme = "light" | "dark";

async function mount(opts: {
  onAuthenticated?: () => void;
  auth?: AuthClient;
  connection?: string | null;
  initialMode?: "signin" | "create";
  scheme?: Scheme;
} = {}): Promise<ReactTestRenderer> {
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
          <ConnectionProvider
            store={connectionStore(opts.connection ?? SERVER)}
          >
            <SessionProvider
              store={sessionStore()}
              authClient={opts.auth ?? authClient()}
            >
              <SignInScreen
                onAuthenticated={opts.onAuthenticated ?? (() => {})}
                {...(opts.initialMode ? { initialMode: opts.initialMode } : {})}
              />
            </SessionProvider>
          </ConnectionProvider>
        </ThemeProvider>
      </SafeAreaProvider>,
    );
    // Flush the connection + session hydration `.then` callbacks.
    await new Promise((r) => setTimeout(r, 0));
  });
  return tree;
}

function field(tree: ReactTestRenderer, label: string) {
  return tree.root.find((n) => n.props.accessibilityLabel === label);
}
function setText(tree: ReactTestRenderer, label: string, text: string): void {
  act(() => {
    (field(tree, label).props.onChangeText as (t: string) => void)(text);
  });
}
const SUBMIT_LABELS = [
  "Sign in",
  "Create account",
  "Signing in…",
  "Creating account…",
];
function submit(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityRole === "button" &&
      typeof n.props.onPress === "function" &&
      SUBMIT_LABELS.includes(n.props.accessibilityLabel as string),
  );
}
function modeTab(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityRole === "radio" &&
      n.props.accessibilityLabel === label,
  );
}
async function pressSubmit(tree: ReactTestRenderer): Promise<void> {
  await act(async () => {
    (submit(tree).props.onPress as () => void)();
    await new Promise((r) => setTimeout(r, 0));
  });
}
function texts(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string);
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
});

// ─── Validation ──────────────────────────────────────────────────────────────

describe("client-side validation before any network call", () => {
  it("blocks submit and shows inline errors for a bad email and short password", async () => {
    const auth = authClient();
    const tree = await mount({ auth });
    setText(tree, "Email", "not-an-email");
    setText(tree, "Password", "short");
    await pressSubmit(tree);

    const t = texts(tree);
    expect(t).toContain("Enter a valid email address.");
    expect(t).toContain("Use a password of 8 to 128 characters.");
    expect(auth.signIn).not.toHaveBeenCalled();
  });

  it("rejects an over-long password without a network call", async () => {
    const auth = authClient();
    const tree = await mount({ auth });
    setText(tree, "Email", "alice@example.com");
    setText(tree, "Password", "x".repeat(129));
    await pressSubmit(tree);

    expect(texts(tree)).toContain("Use a password of 8 to 128 characters.");
    expect(auth.signIn).not.toHaveBeenCalled();
  });
});

// ─── Server-scoped auth + post-auth routing ──────────────────────────────────

describe("server-scoped auth", () => {
  it("shows which server it will authenticate against", async () => {
    const tree = await mount({ connection: SERVER });
    expect(texts(tree)).toContain("Signing in to home.example.net");
  });

  it("signs in against the connected base URL and routes onward", async () => {
    const auth = authClient();
    const onAuthenticated = jest.fn();
    const tree = await mount({ auth, onAuthenticated });
    setText(tree, "Email", "alice@example.com");
    setText(tree, "Password", "a-good-password");
    await pressSubmit(tree);

    expect(auth.signIn).toHaveBeenCalledWith(
      SERVER,
      "alice@example.com",
      "a-good-password",
    );
    expect(onAuthenticated).toHaveBeenCalled();
  });

  it("creates an account against the connected base URL and routes onward", async () => {
    const auth = authClient();
    const onAuthenticated = jest.fn();
    const tree = await mount({ auth, onAuthenticated, initialMode: "create" });
    setText(tree, "Email", "new@example.com");
    setText(tree, "Password", "a-good-password");
    await pressSubmit(tree);

    expect(auth.createAccount).toHaveBeenCalledWith(
      SERVER,
      "new@example.com",
      "a-good-password",
    );
    expect(onAuthenticated).toHaveBeenCalled();
  });
});

// ─── Error surface ───────────────────────────────────────────────────────────

describe("error surface (clear, retryable, non-enumerating)", () => {
  it("shows the identical 401 message for a wrong password and an unknown email", async () => {
    const message = "That email or password didn't match. Check them and try again.";
    const wrongPassword = await mount({
      auth: authClient({ signIn: rejectWith(401) }),
    });
    setText(wrongPassword, "Email", "alice@example.com");
    setText(wrongPassword, "Password", "wrong-password");
    await pressSubmit(wrongPassword);
    expect(texts(wrongPassword)).toContain(message);

    const unknownEmail = await mount({
      auth: authClient({ signIn: rejectWith(401) }),
    });
    setText(unknownEmail, "Email", "ghost@example.com");
    setText(unknownEmail, "Password", "a-good-password");
    await pressSubmit(unknownEmail);
    expect(texts(unknownEmail)).toContain(message);
  });

  it("surfaces a sign-in affordance and flips to sign-in mode on a 409", async () => {
    const auth = authClient({ createAccount: rejectWith(409) });
    const tree = await mount({ auth, initialMode: "create" });
    setText(tree, "Email", "taken@example.com");
    setText(tree, "Password", "a-good-password");
    await pressSubmit(tree);

    expect(texts(tree)).toContain("An account already exists for this email.");
    const instead = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Sign in instead" &&
        typeof n.props.onPress === "function",
    );
    act(() => {
      (instead.props.onPress as () => void)();
    });
    // Mode flipped to sign-in: the submit button now reads "Sign in".
    expect(submit(tree).props.accessibilityLabel).toBe("Sign in");
  });

  it("shows a generic message on a 422", async () => {
    const auth = authClient({ signIn: rejectWith(422) });
    const tree = await mount({ auth });
    setText(tree, "Email", "alice@example.com");
    setText(tree, "Password", "a-good-password");
    await pressSubmit(tree);
    expect(texts(tree)).toContain("Check your details and try again.");
  });

  it("shows a retryable message on a network failure (never a dead-end)", async () => {
    const auth = authClient({
      signIn: jest.fn(async () => {
        throw new TypeError("Network request failed");
      }),
    });
    const tree = await mount({ auth });
    setText(tree, "Email", "alice@example.com");
    setText(tree, "Password", "a-good-password");
    await pressSubmit(tree);
    expect(texts(tree)).toContain(
      "Couldn't reach home.example.net. Check your connection and try again.",
    );
  });
});

// ─── Accessibility + light/dark parity ───────────────────────────────────────

describe("accessibility + light/dark parity", () => {
  it("labels the email, password, mode toggle, and submit", async () => {
    const tree = await mount();
    const labels = tree.root
      .findAll((n) => !!n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);
    expect(labels).toEqual(
      expect.arrayContaining(["Email", "Password", "Sign in", "Create account"]),
    );
  });

  it("uses secure text entry on the password field", async () => {
    const tree = await mount();
    expect(field(tree, "Password").props.secureTextEntry).toBe(true);
  });

  it("gives the submit a ≥44pt tap target", async () => {
    const tree = await mount();
    expect(flattenStyle(submit(tree).props.style).minHeight).toBe(44);
  });

  it("marks the mode tabs as a radio group selection", async () => {
    const tree = await mount({ initialMode: "signin" });
    expect(modeTab(tree, "Sign in").props.accessibilityState).toEqual({
      selected: true,
    });
    expect(modeTab(tree, "Create account").props.accessibilityState).toEqual({
      selected: false,
    });
  });

  it("renders the email field with the light then dark text colour", async () => {
    const light = await mount({ scheme: "light" });
    expect(flattenStyle(field(light, "Email").props.style).color).toBe(
      lightPalette.text,
    );
    const dark = await mount({ scheme: "dark" });
    expect(flattenStyle(field(dark, "Email").props.style).color).toBe(
      darkPalette.text,
    );
  });
});

// ─── Privacy: no secret in logs ──────────────────────────────────────────────

describe("privacy", () => {
  it("never writes the password or token to logs", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      const tree = await mount({ auth: authClient({ signIn: rejectWith(401) }) });
      setText(tree, "Email", "alice@example.com");
      setText(tree, "Password", "super-secret-pw");
      await pressSubmit(tree);
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          const line = call.map((c) => String(c)).join(" ");
          expect(line).not.toContain("super-secret-pw");
          expect(line).not.toContain(RECORD.token);
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});
