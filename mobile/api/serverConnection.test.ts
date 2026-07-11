/**
 * Tests for server-URL validation and the reachability probe (FTY-107).
 *
 * Validation is a trust boundary: both the typed address and the scanned QR
 * payload are untrusted, so non-`http(s)` schemes, malformed strings, and empty
 * input must be rejected *before* any network call. The probe must treat a
 * timeout, a network failure, a non-2xx status, and a non-Slacks body all as
 * unreachable, and confirm Slacks via the `{"status":"ok"}` liveness body.
 */

import {
  DEFAULT_PROBE_TIMEOUT_MS,
  displayHost,
  probeServer,
  validateServerUrl,
} from "./serverConnection";

describe("validateServerUrl — accepted + normalized", () => {
  it("accepts an https URL and strips a trailing slash", () => {
    expect(validateServerUrl("https://slacks.example.com/")).toEqual({
      ok: true,
      url: "https://slacks.example.com",
    });
  });

  it("accepts http with an explicit port and a path", () => {
    expect(validateServerUrl("http://192.168.1.10:8000/slacks/")).toEqual({
      ok: true,
      url: "http://192.168.1.10:8000/slacks",
    });
  });

  it("lowercases the scheme and host and trims surrounding whitespace", () => {
    expect(validateServerUrl("  HTTPS://Slacks.Example.COM  ")).toEqual({
      ok: true,
      url: "https://slacks.example.com",
    });
  });

  it("drops a query string and fragment a base URL should not carry", () => {
    expect(validateServerUrl("https://srv.example.com/?next=/x#frag")).toEqual({
      ok: true,
      url: "https://srv.example.com",
    });
  });
});

describe("validateServerUrl — rejected (untrusted input)", () => {
  it("rejects empty / whitespace input", () => {
    expect(validateServerUrl("")).toEqual({
      ok: false,
      reason: "Enter your server's address.",
    });
    expect(validateServerUrl("   ")).toEqual({
      ok: false,
      reason: "Enter your server's address.",
    });
  });

  it("rejects a non-http(s) scheme (javascript:)", () => {
    const result = validateServerUrl("javascript:alert(1)");
    expect(result.ok).toBe(false);
    expect((result as { reason: string }).reason).toBe(
      "Use an http:// or https:// address.",
    );
  });

  it("rejects file: and app deep-link schemes", () => {
    expect(validateServerUrl("file:///etc/passwd").ok).toBe(false);
    expect(validateServerUrl("slacks://connect?url=evil").ok).toBe(false);
    expect(validateServerUrl("ftp://host/x").ok).toBe(false);
  });

  it("rejects a malformed string with no scheme", () => {
    expect(validateServerUrl("not a url")).toEqual({
      ok: false,
      reason: "That doesn't look like a valid server address.",
    });
    expect(validateServerUrl("localhost:8000").ok).toBe(false);
  });
});

/** A fetch stub returning a Slacks-shaped healthz response. */
function jsonFetch(
  status: number,
  body: unknown,
): jest.MockedFunction<typeof fetch> {
  return jest.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as jest.MockedFunction<typeof fetch>;
}

describe("probeServer", () => {
  it("returns reachable on 200 with the Slacks liveness body and hits /healthz", async () => {
    const fetchImpl = jsonFetch(200, { status: "ok" });
    await expect(
      probeServer("https://srv.example.com", { fetchImpl }),
    ).resolves.toBe("reachable");
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://srv.example.com/healthz",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("returns unreachable on a 200 whose body is not the Slacks health shape", async () => {
    const fetchImpl = jsonFetch(200, { hello: "world" });
    await expect(
      probeServer("https://srv.example.com", { fetchImpl }),
    ).resolves.toBe("unreachable");
  });

  it("returns unreachable on a non-2xx status", async () => {
    const fetchImpl = jsonFetch(503, { detail: "down" });
    await expect(
      probeServer("https://srv.example.com", { fetchImpl }),
    ).resolves.toBe("unreachable");
  });

  it("returns unreachable on a network-layer failure", async () => {
    const fetchImpl = jest.fn(async () => {
      throw new TypeError("Network request failed");
    }) as unknown as typeof fetch;
    await expect(
      probeServer("https://srv.example.com", { fetchImpl }),
    ).resolves.toBe("unreachable");
  });

  it("aborts and returns unreachable when the request exceeds the timeout", async () => {
    jest.useFakeTimers();
    try {
      const fetchImpl = jest.fn(
        (_url: string, opts?: { signal?: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            opts?.signal?.addEventListener("abort", () =>
              reject(new Error("aborted")),
            );
          }),
      ) as unknown as typeof fetch;
      const pending = probeServer("https://slow.example.com", {
        fetchImpl,
        timeoutMs: 1000,
      });
      jest.advanceTimersByTime(1000);
      await expect(pending).resolves.toBe("unreachable");
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("displayHost", () => {
  it("returns the host (with port) for the error message", () => {
    expect(displayHost("http://192.168.1.10:8000/slacks")).toBe(
      "192.168.1.10:8000",
    );
    expect(displayHost("https://slacks.example.com")).toBe("slacks.example.com");
  });

  it("exposes a sensible default timeout", () => {
    expect(DEFAULT_PROBE_TIMEOUT_MS).toBeGreaterThan(0);
  });
});
