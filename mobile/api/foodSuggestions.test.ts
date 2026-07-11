import {
  DEFAULT_FOOD_SUGGESTIONS_LIMIT,
  FoodSuggestionsApiError,
  getFoodSuggestions,
  type FoodSuggestionDTO,
  type FoodSuggestionsResponse,
} from "./foodSuggestions";
import type { ApiSession } from "@/api/client";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const SAVED_SUGGESTION: FoodSuggestionDTO = {
  label: "Greek Yogurt",
  submit_phrase: "yogurt cup",
  saved_food_id: "4d0b6c2a-6b2d-4d3e-8e11-86c1d8e8235f",
  score: 2.4137,
};

const HISTORY_SUGGESTION: FoodSuggestionDTO = {
  label: "Oatmeal",
  submit_phrase: "bowl of oatmeal",
  saved_food_id: null,
  score: 1.1,
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

describe("getFoodSuggestions", () => {
  it("GETs the token-scoped /api/food-suggestions endpoint with the default limit", async () => {
    const response: FoodSuggestionsResponse = {
      items: [SAVED_SUGGESTION, HISTORY_SUGGESTION],
      limit: DEFAULT_FOOD_SUGGESTIONS_LIMIT,
    };
    const fetchMock = jest.fn().mockResolvedValue(okResponse(response));

    const result = await getFoodSuggestions(SESSION, undefined, fetchMock);

    expect(result).toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    // Not user-scoped: the bearer token identifies the user, so no user id path.
    expect(url).toBe("https://api.example.test/api/food-suggestions?limit=8");
    expect(url).not.toContain("/users/");
    expect(init.method).toBe("GET");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
  });

  it("passes an explicit limit through", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ items: [], limit: 5 }));

    await getFoodSuggestions(SESSION, 5, fetchMock);

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain("limit=5");
  });

  it("returns an empty items list when the user has no candidates", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ items: [], limit: 8 }));

    const result = await getFoodSuggestions(SESSION, undefined, fetchMock);
    expect(result.items).toHaveLength(0);
  });

  it("maps a 401 to a session-expired error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    let caught!: FoodSuggestionsApiError;
    await getFoodSuggestions(SESSION, undefined, fetchMock).catch((e: unknown) => {
      caught = e as FoodSuggestionsApiError;
    });
    expect(caught).toBeInstanceOf(FoodSuggestionsApiError);
    expect(caught.status).toBe(401);
    expect(caught.message).toContain("session has expired");
  });

  it("maps an unexpected status to a generic error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(503));
    let caught!: FoodSuggestionsApiError;
    await getFoodSuggestions(SESSION, undefined, fetchMock).catch((e: unknown) => {
      caught = e as FoodSuggestionsApiError;
    });
    expect(caught.status).toBe(503);
    expect(caught.message).toContain("503");
  });
});
