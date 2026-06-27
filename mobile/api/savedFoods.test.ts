import {
  SavedFoodApiError,
  saveFood,
  searchSavedFoods,
  type SavedFoodSession,
  type SaveFoodRequest,
  type SavedFoodDTO,
} from "./savedFoods";

const SESSION: SavedFoodSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const NUTRITION = {
  calories: 150,
  protein_g: 20,
  carbs_g: 8,
  fat_g: 4,
  serving_size: 1,
  serving_unit: "cup",
};

const REQUEST: SaveFoodRequest = {
  name: "Greek yogurt",
  phrase: "a cup of greek yogurt",
  nutrition: NUTRITION,
};

const SAVED_FOOD: SavedFoodDTO = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  user_id: SESSION.userId,
  name: "Greek yogurt",
  calories: 150,
  protein_g: 20,
  carbs_g: 8,
  fat_g: 4,
  serving_size: 1,
  serving_unit: "cup",
  source: "saved_from_correction",
  created_at: "2026-06-27T10:00:00Z",
  updated_at: "2026-06-27T10:00:00Z",
};

function okResponse(body: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    json: async () => body,
  } as unknown as Response;
}

function errorResponse(status: number, body: unknown = { detail: "error" }): Response {
  return {
    ok: false,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("saveFood", () => {
  it("POSTs the request to the owner's saved-foods endpoint with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(SAVED_FOOD, 201));

    const result = await saveFood(SESSION, REQUEST, fetchMock);

    expect(result).toEqual(SAVED_FOOD);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/saved-foods",
    );
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual(REQUEST);
  });

  it("maps a 401 to a session-expired error without echoing request data", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(saveFood(SESSION, REQUEST, fetchMock)).rejects.toMatchObject({
      name: "SavedFoodApiError",
      status: 401,
    });
    let caughtErr!: SavedFoodApiError;
    await saveFood(SESSION, REQUEST, fetchMock).catch((e: unknown) => {
      caughtErr = e as SavedFoodApiError;
    });
    expect(caughtErr.message).toContain("session has expired");
    expect(caughtErr.message).not.toContain("greek yogurt");
  });

  it("maps a 422 to a validation error without echoing the payload", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(422, { detail: [{ msg: "value error" }] }),
    );
    await expect(saveFood(SESSION, REQUEST, fetchMock)).rejects.toBeInstanceOf(
      SavedFoodApiError,
    );
    let caughtErr!: SavedFoodApiError;
    await saveFood(SESSION, REQUEST, fetchMock).catch((e: unknown) => {
      caughtErr = e as SavedFoodApiError;
    });
    expect(caughtErr.status).toBe(422);
    expect(caughtErr.message).not.toContain("Greek yogurt");
  });

  it("maps a 404 (cross-user, fail closed) to an error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(saveFood(SESSION, REQUEST, fetchMock)).rejects.toBeInstanceOf(
      SavedFoodApiError,
    );
  });

  it("maps an unexpected status to a generic error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(503));
    let caughtErr!: SavedFoodApiError;
    await saveFood(SESSION, REQUEST, fetchMock).catch((e: unknown) => {
      caughtErr = e as SavedFoodApiError;
    });
    expect(caughtErr.status).toBe(503);
    expect(caughtErr.message).toContain("503");
  });
});

describe("searchSavedFoods", () => {
  it("GETs the owner's saved-foods endpoint with the encoded query", async () => {
    const response = { items: [SAVED_FOOD], limit: 20 };
    const fetchMock = jest.fn().mockResolvedValue(okResponse(response));

    const result = await searchSavedFoods(SESSION, "greek", fetchMock);

    expect(result).toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/saved-foods?q=greek",
    );
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
    expect(init.method).toBe("GET");
  });

  it("URL-encodes the query string", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ items: [], limit: 20 }));

    await searchSavedFoods(SESSION, "greek yogurt & oats", fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("q=greek%20yogurt%20%26%20oats");
  });

  it("returns an empty items list when nothing matches", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ items: [], limit: 20 }));

    const result = await searchSavedFoods(SESSION, "zzz", fetchMock);
    expect(result.items).toHaveLength(0);
  });

  it("maps a 401 to a session-expired error without echoing the query", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    let caughtErr!: SavedFoodApiError;
    await searchSavedFoods(SESSION, "my food", fetchMock).catch((e: unknown) => {
      caughtErr = e as SavedFoodApiError;
    });
    expect(caughtErr).toBeInstanceOf(SavedFoodApiError);
    expect(caughtErr.status).toBe(401);
    expect(caughtErr.message).not.toContain("my food");
  });

  it("maps a 404 (cross-user, fail closed) to an error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(
      searchSavedFoods(SESSION, "test", fetchMock),
    ).rejects.toBeInstanceOf(SavedFoodApiError);
  });
});
