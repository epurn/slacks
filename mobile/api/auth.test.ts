import {
  AuthApiError,
  createAccount,
  normalizeServerUrl,
  signIn,
  userIdFromToken,
} from "./auth";

const USER_ID = "11111111-1111-1111-1111-111111111111";
const SERVER = "https://slacks.example.test";

/** Encode a string as base64url (no padding), the token segment encoding. */
function base64url(value: string): string {
  const encode = (globalThis as unknown as { btoa: (s: string) => string })
    .btoa;
  return encode(value)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Build a fixture bearer token `<payload_b64url>.<signature_b64url>`. */
function makeToken(sub: string): string {
  const payload = base64url(
    JSON.stringify({ sub, iat: 1_700_000_000, exp: 1_700_604_800 }),
  );
  return `${payload}.${base64url("not-a-real-signature")}`;
}

const TOKEN = makeToken(USER_ID);

function okResponse(status: number, body: unknown): Response {
  return {
    ok: true,
    status,
    json: async () => body,
  } as unknown as Response;
}

function errorResponse(status: number): Response {
  return {
    ok: false,
    status,
    json: async () => ({ detail: "error" }),
  } as unknown as Response;
}

describe("normalizeServerUrl", () => {
  it("trims whitespace and strips trailing slashes", () => {
    expect(normalizeServerUrl("  https://s.test/  ")).toBe("https://s.test");
    expect(normalizeServerUrl("https://s.test///")).toBe("https://s.test");
    expect(normalizeServerUrl("https://s.test")).toBe("https://s.test");
  });
});

describe("userIdFromToken", () => {
  it("reads the `sub` claim from the token payload", () => {
    expect(userIdFromToken(TOKEN)).toBe(USER_ID);
  });

  it("throws (without leaking the token) on a malformed token", () => {
    for (const bad of ["", "no-dot", "a.b.c", `${"!@#"}.sig`]) {
      try {
        userIdFromToken(bad);
        throw new Error(`expected userIdFromToken to throw for ${bad}`);
      } catch (error) {
        expect(error).toBeInstanceOf(AuthApiError);
        if (bad !== "") {
          expect((error as AuthApiError).message).not.toContain(bad);
        }
      }
    }
  });
});

describe("createAccount", () => {
  it("POSTs to the bound server and returns a normalized session", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      okResponse(201, {
        user: { id: USER_ID, created_at: "2026-06-28T00:00:00Z" },
        token: { access_token: TOKEN, token_type: "bearer", expires_in: 604800 },
      }),
    );

    const result = await createAccount(
      `${SERVER}/`,
      "alice@example.com",
      "a-good-password",
      fetchMock,
    );

    expect(result).toEqual({ serverUrl: SERVER, token: TOKEN, userId: USER_ID });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/auth/register`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "alice@example.com",
      password: "a-good-password",
    });
  });

  it("maps 409 to an already-exists message (register-only)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(409));
    await expect(
      createAccount(SERVER, "a@b.test", "password1", fetchMock),
    ).rejects.toMatchObject({ name: "AuthApiError", status: 409 });
  });

  it("maps 422 to a validation message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(
      createAccount(SERVER, "bad", "short", fetchMock),
    ).rejects.toMatchObject({ status: 422 });
  });

  it("never echoes the email or password into an error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await createAccount(SERVER, "alice@example.com", "s3cr3t-pw", fetchMock);
      throw new Error("expected createAccount to throw");
    } catch (error) {
      const message = (error as AuthApiError).message;
      expect(message).not.toContain("alice@example.com");
      expect(message).not.toContain("s3cr3t-pw");
    }
  });

  it("fails closed on a 2xx body missing the token or user id", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse(201, { user: {}, token: {} }));
    await expect(
      createAccount(SERVER, "a@b.test", "password1", fetchMock),
    ).rejects.toBeInstanceOf(AuthApiError);
  });
});

describe("signIn", () => {
  it("POSTs to the bound server and derives userId from the token claim", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      okResponse(200, {
        access_token: TOKEN,
        token_type: "bearer",
        expires_in: 604800,
      }),
    );

    const result = await signIn(
      `${SERVER}//`,
      "alice@example.com",
      "a-good-password",
      fetchMock,
    );

    expect(result).toEqual({ serverUrl: SERVER, token: TOKEN, userId: USER_ID });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${SERVER}/api/auth/login`);
    expect(init.method).toBe("POST");
  });

  it("returns the identical 401 message for unknown email and wrong password", async () => {
    // Both cases surface as a 401 from the backend (no existence oracle); the
    // client must not differentiate them.
    const unknownEmail = jest.fn().mockResolvedValue(errorResponse(401));
    const wrongPassword = jest.fn().mockResolvedValue(errorResponse(401));

    const a = await signIn(SERVER, "nobody@x.test", "whatever1", unknownEmail)
      .then(() => null)
      .catch((e: AuthApiError) => e);
    const b = await signIn(SERVER, "alice@x.test", "wrong-pass", wrongPassword)
      .then(() => null)
      .catch((e: AuthApiError) => e);

    expect(a).toBeInstanceOf(AuthApiError);
    expect(b).toBeInstanceOf(AuthApiError);
    expect((a as AuthApiError).message).toBe((b as AuthApiError).message);
    // The message must not reveal whether the account exists.
    const message = (a as AuthApiError).message.toLowerCase();
    expect(message).not.toContain("unknown");
    expect(message).not.toContain("no account");
    expect(message).not.toContain("not found");
    expect(message).not.toContain("exist");
  });
});

describe("no secret leaks to logs", () => {
  it("logs nothing during happy or error paths", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      const ok = jest
        .fn()
        .mockResolvedValue(okResponse(200, { access_token: TOKEN }));
      await signIn(SERVER, "a@b.test", "password1", ok);

      const bad = jest.fn().mockResolvedValue(errorResponse(401));
      await signIn(SERVER, "a@b.test", "password1", bad).catch(() => {});

      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          const text = call.map((c) => String(c)).join(" ");
          expect(text).not.toContain(TOKEN);
          expect(text).not.toContain("password1");
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});
