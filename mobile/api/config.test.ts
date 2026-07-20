/**
 * Tests for the connection-aware base-URL accessor (FTY-107).
 *
 * `resolveApiBaseUrl()` must prefer the persisted runtime connection over the
 * build-time default while staying synchronous (so existing API clients keep
 * calling it unchanged), keep the trailing-slash normalization, and fall back to
 * the build-time `extra.apiBaseUrl` / localhost default when no connection is set.
 */

// Mutable Expo `extra` so a test can exercise the build-time fallback path.
const mockExtra: { apiBaseUrl?: string } = {};
jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    get expoConfig() {
      return { extra: mockExtra };
    },
  },
}));

// eslint-disable-next-line import/first
import {
  DEFAULT_API_BASE_URL,
  defaultApiBaseUrl,
  resolveApiBaseUrl,
  setConnectedBaseUrl,
} from "./config";

afterEach(() => {
  setConnectedBaseUrl(null);
  delete mockExtra.apiBaseUrl;
});

describe("resolveApiBaseUrl — no connection (build-time fallback)", () => {
  it("falls back to the localhost default when nothing is configured", () => {
    expect(resolveApiBaseUrl()).toBe(DEFAULT_API_BASE_URL);
  });

  it("uses the build-time extra.apiBaseUrl when set, normalized", () => {
    mockExtra.apiBaseUrl = "https://build.example.com/";
    expect(resolveApiBaseUrl()).toBe("https://build.example.com");
  });
});

describe("resolveApiBaseUrl — persisted connection preferred", () => {
  it("prefers the connected URL over the build-time default", () => {
    mockExtra.apiBaseUrl = "https://build.example.com";
    setConnectedBaseUrl("https://my-server.example.com");
    expect(resolveApiBaseUrl()).toBe("https://my-server.example.com");
  });

  it("normalizes the connected URL (trims, strips trailing slash)", () => {
    setConnectedBaseUrl("  https://my-server.example.com/  ");
    expect(resolveApiBaseUrl()).toBe("https://my-server.example.com");
  });

  it("clearing the connection (null) restores the build-time fallback", () => {
    setConnectedBaseUrl("https://my-server.example.com");
    setConnectedBaseUrl(null);
    expect(resolveApiBaseUrl()).toBe(DEFAULT_API_BASE_URL);
  });

  it("treats an empty/whitespace connection as no connection", () => {
    setConnectedBaseUrl("   ");
    expect(resolveApiBaseUrl()).toBe(DEFAULT_API_BASE_URL);
  });
});

describe("defaultApiBaseUrl — the 'back to default' address (FTY-405)", () => {
  it("ignores an established connection so it always offers a real way back", () => {
    setConnectedBaseUrl("https://my-server.example.com");
    expect(defaultApiBaseUrl()).toBe(DEFAULT_API_BASE_URL);
  });

  it("returns the normalized build-time extra.apiBaseUrl when one is set", () => {
    mockExtra.apiBaseUrl = "https://build.example.com/";
    setConnectedBaseUrl("https://my-server.example.com");
    expect(defaultApiBaseUrl()).toBe("https://build.example.com");
  });
});
