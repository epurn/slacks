import {
  LogEventApiError,
  createLogEvent,
  getLogEventClarification,
  listTodayLogEvents,
  type LogEventDTO,
  type LogEventSession,
} from "./logEvents";

const SESSION: LogEventSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const DTO: LogEventDTO = {
  id: "33333333-3333-3333-3333-333333333333",
  user_id: SESSION.userId,
  raw_text: "two eggs and toast",
  status: "pending",
  created_at: "2026-06-26T08:00:00Z",
  updated_at: "2026-06-26T08:00:00Z",
};

function okResponse(body: unknown, status = 200): Response {
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

describe("listTodayLogEvents", () => {
  it("GETs the owner's events with a bearer token, defaulting the day", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([DTO]));

    const result = await listTodayLogEvents(SESSION, undefined, fetchMock);

    expect(result).toEqual([DTO]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("includes an explicit day as a query parameter", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([]));

    await listTodayLogEvents(SESSION, "2026-06-26", fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/log-events?day=2026-06-26");
  });

  it("maps a 401 to a session-expired error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      listTodayLogEvents(SESSION, undefined, fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 401 });
  });

  it("maps a 404 to a LogEventApiError that fails closed", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      listTodayLogEvents(SESSION, undefined, fetchMock),
    ).rejects.toBeInstanceOf(LogEventApiError);
  });
});

describe("createLogEvent", () => {
  it("POSTs the raw text to the owner's endpoint with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));

    const result = await createLogEvent(
      SESSION,
      "two eggs and toast",
      undefined,
      fetchMock,
    );

    expect(result).toEqual(DTO);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events",
    );
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({
      raw_text: "two eggs and toast",
    });
  });

  it("sends the idempotency key in the body when supplied (FTY-096)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));

    await createLogEvent(
      SESSION,
      "two eggs and toast",
      "01J-some-key",
      fetchMock,
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      raw_text: "two eggs and toast",
      idempotency_key: "01J-some-key",
    });
  });

  it("treats a 200 idempotent replay the same as a 201 create", async () => {
    // A replay of an already-accepted key returns 200 with the existing event.
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 200));

    const result = await createLogEvent(SESSION, "two eggs", "key-1", fetchMock);

    expect(result).toEqual(DTO);
  });

  it("maps a 422 to a nonjudgmental LogEventApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(
      createLogEvent(SESSION, "   ", undefined, fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 422 });
  });

  it("does not echo the user's raw text into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await createLogEvent(SESSION, "a very private note", undefined, fetchMock);
      throw new Error("expected createLogEvent to throw");
    } catch (error) {
      const message = (error as LogEventApiError).message;
      expect(message).not.toContain("a very private note");
    }
  });
});

describe("getLogEventClarification", () => {
  it("GETs the owner-scoped clarification read for the event with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      okResponse({ questions: [{ text: "How much peanut butter?" }] }),
    );

    const result = await getLogEventClarification(SESSION, "event-1", fetchMock);

    expect(result).toEqual({ questions: [{ text: "How much peanut butter?" }] });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/event-1/clarification",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("returns an empty question list for an event with no clarification rows", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse({ questions: [] }));

    const result = await getLogEventClarification(SESSION, "event-1", fetchMock);

    expect(result).toEqual({ questions: [] });
  });

  it("maps a 404 to a fail-closed LogEventApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      getLogEventClarification(SESSION, "event-1", fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 404 });
  });
});
