import {
  LogEventApiError,
  answerClarification,
  createLogEvent,
  createLogEventWithImages,
  deleteLogEvent,
  getLogEventClarification,
  listTodayLogEvents,
  listTodayLogEventEntries,
  type LogEventDTO,
  type LogEventEntryDTO,
  type LogEventSession,
  type SubmissionImage,
} from "./logEvents";
import { setUnauthorizedHandler } from "./client";

const SESSION: LogEventSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const DTO: LogEventDTO = {
  id: "33333333-3333-3333-3333-333333333333",
  user_id: SESSION.userId,
  raw_text: "two eggs and toast",
  name: null,
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

describe("listTodayLogEventEntries", () => {
  const ENTRY: LogEventEntryDTO = { event: DTO, items: [] };

  it("GETs the owner's by-date entries with a bearer token, defaulting the day", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([ENTRY]));

    const result = await listTodayLogEventEntries(SESSION, undefined, fetchMock);

    expect(result).toEqual([ENTRY]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/by-date",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("includes an explicit day as a query parameter", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([]));

    await listTodayLogEventEntries(SESSION, "2026-06-26", fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/log-events/by-date?day=2026-06-26");
  });

  it("maps a 401 to a session-expired error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      listTodayLogEventEntries(SESSION, undefined, fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 401 });
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

describe("createLogEventWithImages (FTY-383 multipart)", () => {
  const IMAGE_A: SubmissionImage = {
    uri: "file:///a.jpg",
    name: "a.jpg",
    type: "image/jpeg",
  };
  const IMAGE_B: SubmissionImage = {
    uri: "file:///b.png",
    name: "b.png",
    type: "image/png",
  };

  // Read appended FormData parts via the standard `entries()` iterator. (The
  // jest env's FormData stringifies the RN `{ uri, name, type }` file object, so
  // the image parts are asserted by count/name here; the file descriptor's
  // fields are exercised on-device by the Maestro flow.)
  function parts(body: unknown): [string, unknown][] {
    return [...(body as FormData).entries()] as [string, unknown][];
  }
  function payloadPart(body: unknown): Record<string, unknown> {
    const entry = parts(body).find(([name]) => name === "payload");
    return JSON.parse(entry![1] as string) as Record<string, unknown>;
  }
  function imageParts(body: unknown): unknown[] {
    return parts(body)
      .filter(([name]) => name === "image")
      .map(([, value]) => value);
  }

  afterEach(() => {
    setUnauthorizedHandler(null);
  });

  it("POSTs a multipart body: JSON payload part + one image part per image", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));

    const result = await createLogEventWithImages(
      SESSION,
      "2 of these bars",
      [IMAGE_A, IMAGE_B],
      false,
      "key-1",
      fetchMock,
    );

    expect(result).toEqual(DTO);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // Save flag rides the query string (default false).
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events?save=false",
    );
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    // No JSON Content-Type — FormData sets multipart/form-data + boundary.
    expect(headers["Content-Type"]).toBeUndefined();

    expect(payloadPart(init.body)).toEqual({
      raw_text: "2 of these bars",
      idempotency_key: "key-1",
    });
    // One `image` part per attached image (repeated part name), in order.
    expect(imageParts(init.body)).toHaveLength(2);
  });

  it("omits raw_text from the payload when the text is empty (image-only)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));

    await createLogEventWithImages(SESSION, "   ", [IMAGE_A], false, "key-2", fetchMock);

    expect(payloadPart((fetchMock.mock.calls[0] as [string, RequestInit])[1].body)).toEqual({
      idempotency_key: "key-2",
    });
  });

  it("sends save=true in the query string when the retention flag is set", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));
    await createLogEventWithImages(SESSION, "bar", [IMAGE_A], true, "key-3", fetchMock);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("?save=true");
  });

  it("treats a 200 idempotent replay the same as a 201 create", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 200));
    const result = await createLogEventWithImages(
      SESSION,
      "bar",
      [IMAGE_A],
      false,
      "key-4",
      fetchMock,
    );
    expect(result).toEqual(DTO);
  });

  it("maps a non-2xx status to a content-free LogEventApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(413));
    await expect(
      createLogEventWithImages(SESSION, "bar", [IMAGE_A], false, "key-5", fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 413 });
  });

  it("clears the session (unauthorized handler) on a 401, like the JSON path", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      createLogEventWithImages(SESSION, "bar", [IMAGE_A], false, "key-6", fetchMock),
    ).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("propagates a network-layer failure (image submits are online-only, never queued)", async () => {
    const fetchMock = jest.fn().mockRejectedValue(new TypeError("Network request failed"));
    await expect(
      createLogEventWithImages(SESSION, "bar", [IMAGE_A], false, "key-7", fetchMock),
    ).rejects.toBeInstanceOf(TypeError);
  });

  it("never echoes the user's raw text into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await createLogEventWithImages(
        SESSION,
        "a very private note",
        [IMAGE_A],
        false,
        "key-8",
        fetchMock,
      );
      throw new Error("expected createLogEventWithImages to throw");
    } catch (error) {
      expect((error as LogEventApiError).message).not.toContain("a very private note");
    }
  });
});

describe("getLogEventClarification", () => {
  it("GETs the owner-scoped clarification read carrying the question id, text, and chips", async () => {
    const question = {
      id: "q-1",
      text: "How much peanut butter?",
      options: ["1 tbsp", "2 tbsp"],
    };
    const fetchMock = jest.fn().mockResolvedValue(
      okResponse({ questions: [question] }),
    );

    const result = await getLogEventClarification(SESSION, "event-1", fetchMock);

    expect(result).toEqual({ questions: [question] });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/event-1/clarification",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("carries a question with an empty options list (deterministic backend-raised)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      okResponse({ questions: [{ id: "q-2", text: "Which meal?", options: [] }] }),
    );

    const result = await getLogEventClarification(SESSION, "event-1", fetchMock);

    expect(result.questions[0]?.options).toEqual([]);
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

describe("answerClarification", () => {
  const PROCESSING: LogEventDTO = {
    ...DTO,
    raw_text: "crackers and peanut butter",
    name: null,
    status: "processing",
  };

  it("POSTs question_id + answer to the owner-scoped answers endpoint with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(PROCESSING, 201));

    const result = await answerClarification(
      SESSION,
      "event-1",
      "q-1",
      "2 tbsp",
      fetchMock,
    );

    expect(result).toEqual(PROCESSING);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/event-1/clarification/answers",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      question_id: "q-1",
      answer: "2 tbsp",
    });
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("treats a 200 idempotent replay the same as a 201 fresh answer", async () => {
    const completed: LogEventDTO = { ...PROCESSING, status: "completed" };
    const fetchMock = jest.fn().mockResolvedValue(okResponse(completed, 200));

    const result = await answerClarification(
      SESSION,
      "event-1",
      "q-1",
      "2 tbsp",
      fetchMock,
    );

    expect(result.status).toBe("completed");
  });

  it("does not echo the user's answer into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(
      answerClarification(SESSION, "event-1", "q-1", "peanuts", fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError" });
    const error = await answerClarification(
      SESSION,
      "event-1",
      "q-1",
      "peanuts",
      fetchMock,
    ).catch((e: LogEventApiError) => e);
    expect((error as LogEventApiError).message).not.toContain("peanuts");
  });

  it("maps a 404 to a fail-closed LogEventApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      answerClarification(SESSION, "event-1", "q-1", "2 tbsp", fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 404 });
  });
});

describe("deleteLogEvent", () => {
  // The FTY-321 soft-void contract answers 204 No Content with an empty body,
  // so the client must not try to parse a body on success.
  function noContentResponse(): Response {
    return {
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("204 has no body to parse");
      },
    } as unknown as Response;
  }

  it("DELETEs the owner-scoped event and resolves void on 204", async () => {
    const fetchMock = jest.fn().mockResolvedValue(noContentResponse());

    await expect(
      deleteLogEvent(SESSION, "44444444-4444-4444-4444-444444444444", fetchMock),
    ).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/44444444-4444-4444-4444-444444444444",
    );
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
    // No request body on a delete.
    expect(init.body).toBeUndefined();
  });

  it("maps a 404 (cross-user / unknown id) to a fail-closed LogEventApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      deleteLogEvent(SESSION, "unknown-id", fetchMock),
    ).rejects.toMatchObject({ name: "LogEventApiError", status: 404 });
  });

  it("maps a 401 to a session-expired error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    const error = await deleteLogEvent(SESSION, "event-1", fetchMock).catch(
      (e: LogEventApiError) => e,
    );
    expect((error as LogEventApiError).status).toBe(401);
    expect((error as LogEventApiError).message).toMatch(/session has expired/i);
  });
});
