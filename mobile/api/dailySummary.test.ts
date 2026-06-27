import {
  DailySummaryApiError,
  getDailySummary,
  type DailySummaryDTO,
  type DailySummarySession,
} from "./dailySummary";

const SESSION: DailySummarySession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const DTO: DailySummaryDTO = {
  date: "2026-06-27",
  intake: { calories: 1850, protein_g: 120, carbs_g: 180, fat_g: 60 },
  target: { calories: 2000 },
  exercise: { active_calories: 350 },
};

function okResponse(body: unknown, status = 200): Response {
  return { ok: true, status, json: async () => body } as unknown as Response;
}

function errorResponse(status: number): Response {
  return { ok: false, status, json: async () => ({ detail: "error" }) } as unknown as Response;
}

describe("getDailySummary", () => {
  it("GETs today's summary with a bearer token and returns the DTO", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));

    const result = await getDailySummary(SESSION, undefined, fetchMock);

    expect(result).toEqual(DTO);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/daily-summary",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
    expect((init.headers as Record<string, string>).Accept).toBe("application/json");
  });

  it("omits the day query param when no day is provided", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));

    await getDailySummary(SESSION, undefined, fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).not.toContain("?");
  });

  it("appends the day query param when a day is provided", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));

    await getDailySummary(SESSION, "2026-06-27", fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/daily-summary?day=2026-06-27",
    );
  });

  it("encodes the userId and day in the URL", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));
    const session: DailySummarySession = { ...SESSION, userId: "a/b c" };

    await getDailySummary(session, "2026 06 27", fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("/api/users/a%2Fb%20c/daily-summary");
    expect(url).toContain("day=2026%2006%2027");
  });

  it("maps a 401 to a DailySummaryApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(getDailySummary(SESSION, undefined, fetchMock)).rejects.toMatchObject({
      name: "DailySummaryApiError",
      status: 401,
    });
  });

  it("maps a 404 to a DailySummaryApiError that fails closed", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(getDailySummary(SESSION, undefined, fetchMock)).rejects.toBeInstanceOf(
      DailySummaryApiError,
    );
  });

  it("maps a 422 to a nonjudgmental DailySummaryApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(getDailySummary(SESSION, "not-a-date", fetchMock)).rejects.toMatchObject({
      name: "DailySummaryApiError",
      status: 422,
    });
  });

  it("maps an unexpected status to a DailySummaryApiError carrying the status", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(500));
    await expect(getDailySummary(SESSION, undefined, fetchMock)).rejects.toMatchObject({
      name: "DailySummaryApiError",
      status: 500,
    });
  });

  it("never leaks personal figures into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await getDailySummary(SESSION, "2026-06-27", fetchMock);
      throw new Error("expected getDailySummary to throw");
    } catch (error) {
      const message = (error as DailySummaryApiError).message;
      expect(message).not.toContain("1850");
      expect(message).not.toContain("120");
      expect(message).not.toContain("350");
    }
  });
});
