import {
  WeightApiError,
  createWeightEntry,
  listWeightEntries,
  type WeightEntryDTO,
  type WeightSession,
} from "./weightEntries";

const SESSION: WeightSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const DTO: WeightEntryDTO = {
  id: "33333333-3333-3333-3333-333333333333",
  user_id: SESSION.userId,
  weight_kg: 70.5,
  effective_date: "2026-06-27",
  created_at: "2026-06-27T08:00:00Z",
  updated_at: "2026-06-27T08:00:00Z",
};

function okResponse(body: unknown, status = 200): Response {
  return { ok: true, status, json: async () => body } as unknown as Response;
}

function errorResponse(status: number): Response {
  return { ok: false, status, json: async () => ({ detail: "error" }) } as unknown as Response;
}

describe("createWeightEntry", () => {
  it("POSTs the weight and effective_date with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO, 201));

    const result = await createWeightEntry(SESSION, 70.5, "2026-06-27", fetchMock);

    expect(result).toEqual(DTO);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/weight-entries",
    );
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
    expect(JSON.parse(init.body as string)).toEqual({
      weight: 70.5,
      effective_date: "2026-06-27",
    });
  });

  it("maps a 401 to a WeightApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(createWeightEntry(SESSION, 70.5, "2026-06-27", fetchMock)).rejects.toMatchObject({
      name: "WeightApiError",
      status: 401,
    });
  });

  it("maps a 422 to a nonjudgmental WeightApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(createWeightEntry(SESSION, -1, "2026-06-27", fetchMock)).rejects.toBeInstanceOf(
      WeightApiError,
    );
  });

  it("does not echo the submitted weight value into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await createWeightEntry(SESSION, 99.9, "2026-06-27", fetchMock);
      throw new Error("expected createWeightEntry to throw");
    } catch (error) {
      expect((error as WeightApiError).message).not.toContain("99.9");
    }
  });
});

describe("listWeightEntries", () => {
  it("GETs with a bearer token and returns the DTO array", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([DTO]));

    const result = await listWeightEntries(SESSION, "2026-03-28", "2026-06-27", fetchMock);

    expect(result).toEqual([DTO]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/weight-entries?from=2026-03-28&to=2026-06-27",
    );
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("omits query params when from/to are not provided", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([]));

    await listWeightEntries(SESSION, undefined, undefined, fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).not.toContain("?");
  });

  it("sends only the from param when to is omitted", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse([]));

    await listWeightEntries(SESSION, "2026-01-01", undefined, fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("from=2026-01-01");
    expect(url).not.toContain("to=");
  });

  it("maps a 401 to a WeightApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(listWeightEntries(SESSION, undefined, undefined, fetchMock)).rejects.toMatchObject({
      name: "WeightApiError",
      status: 401,
    });
  });

  it("maps a 404 to a WeightApiError that fails closed", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      listWeightEntries(SESSION, undefined, undefined, fetchMock),
    ).rejects.toBeInstanceOf(WeightApiError);
  });
});
