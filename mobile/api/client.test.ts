import { ApiError, authHeaders, request, userScopedUrl } from "./client";
import type { ApiSession } from "./client";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user/with space",
};

function okResponse(body: unknown, status = 200): Response {
  return { ok: true, status, json: async () => body } as unknown as Response;
}

function errorResponse(status: number): Response {
  return {
    ok: false,
    status,
    json: async () => ({ detail: "error" }),
  } as unknown as Response;
}

// Minimal subclass to exercise the name-preservation pattern.
class ThingApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "ThingApiError";
  }
}

describe("authHeaders", () => {
  it("returns the exact JSON header set", () => {
    const headers = authHeaders(SESSION);
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers.Accept).toBe("application/json");
    expect(Object.keys(headers)).toHaveLength(3);
  });
});

describe("userScopedUrl", () => {
  it("encodes the userId in the base path", () => {
    const url = userScopedUrl(SESSION);
    expect(url).toBe(
      "https://api.example.test/api/users/user%2Fwith%20space",
    );
  });

  it("appends a single segment", () => {
    const url = userScopedUrl(SESSION, "profile");
    expect(url).toBe(
      "https://api.example.test/api/users/user%2Fwith%20space/profile",
    );
  });

  it("appends multiple segments joined by /", () => {
    const url = userScopedUrl(SESSION, "target", "override", "reset");
    expect(url).toBe(
      "https://api.example.test/api/users/user%2Fwith%20space/target/override/reset",
    );
  });

  it("preserves encodeURIComponent in a segment passed verbatim", () => {
    const itemId = "item/with space";
    const url = userScopedUrl(
      SESSION,
      `derived-items/food/${encodeURIComponent(itemId)}`,
    );
    expect(url).toContain("derived-items/food/item%2Fwith%20space");
  });
});

describe("ApiError", () => {
  it("carries status and message", () => {
    const err = new ApiError(404, "not found");
    expect(err.status).toBe(404);
    expect(err.message).toBe("not found");
    expect(err.name).toBe("ApiError");
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
  });
});

describe("ApiError subclass", () => {
  it("preserves its own name and satisfies instanceof both the subclass and the base", () => {
    const err = new ThingApiError(401, "session expired");
    expect(err.name).toBe("ThingApiError");
    expect(err.status).toBe(401);
    expect(err).toBeInstanceOf(ThingApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
  });
});

describe("request", () => {
  const onError = (status: number, action: string): ThingApiError => {
    const message =
      status === 401
        ? "Session expired."
        : `Could not ${action} (status ${status}).`;
    return new ThingApiError(status, message);
  };

  it("returns the parsed body on a 2xx response", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ value: 42 }, 200));

    const result = await request<{ value: number }>(
      "https://api.example.test/some-endpoint",
      { method: "GET", headers: {}, action: "get value", onError, fetchImpl: fetchMock },
    );

    expect(result).toEqual({ value: 42 });
  });

  it("throws the caller-supplied error on a non-2xx response", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));

    await expect(
      request<unknown>("https://api.example.test/ep", {
        method: "GET",
        headers: {},
        action: "load data",
        onError,
        fetchImpl: fetchMock,
      }),
    ).rejects.toMatchObject({
      name: "ThingApiError",
      status: 401,
      message: "Session expired.",
    });
  });

  it("passes action to the fallback message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(503));

    await expect(
      request<unknown>("https://api.example.test/ep", {
        method: "GET",
        headers: {},
        action: "load data",
        onError,
        fetchImpl: fetchMock,
      }),
    ).rejects.toMatchObject({
      status: 503,
      message: "Could not load data (status 503).",
    });
  });

  it("includes the body in the request when provided", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse({}));
    const body = JSON.stringify({ foo: "bar" });

    await request<unknown>("https://api.example.test/ep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      action: "post",
      onError,
      fetchImpl: fetchMock,
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe(body);
  });

  it("omits the body from the request when not provided", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse({}));

    await request<unknown>("https://api.example.test/ep", {
      method: "GET",
      headers: {},
      action: "get",
      onError,
      fetchImpl: fetchMock,
    });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
  });

  it("uses the injected fetchImpl", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse({ ok: true }));

    await request<{ ok: boolean }>("https://api.example.test/ep", {
      method: "GET",
      headers: {},
      action: "get",
      onError,
      fetchImpl: fetchMock,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
