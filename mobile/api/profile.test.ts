import {
  ProfileApiError,
  getProfile,
  putProfile,
  type ProfileDTO,
  type ProfileSession,
} from "./profile";
import type { ProfileUpdatePayload } from "@/state/profile";

const SESSION: ProfileSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const PAYLOAD: ProfileUpdatePayload = {
  height_m: 1.75,
  weight_kg: 70,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "America/New_York",
};

const DTO: ProfileDTO = {
  user_id: SESSION.userId,
  height_m: 1.75,
  weight_kg: 70,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "America/New_York",
  updated_at: "2026-06-26T00:00:00Z",
};

function okResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
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

describe("putProfile", () => {
  it("PUTs the canonical payload to the owner's profile with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));

    const result = await putProfile(SESSION, PAYLOAD, fetchMock);

    expect(result).toEqual(DTO);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/profile",
    );
    expect(init.method).toBe("PUT");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual(PAYLOAD);
  });

  it("maps a 422 to a nonjudgmental ProfileApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(putProfile(SESSION, PAYLOAD, fetchMock)).rejects.toMatchObject({
      name: "ProfileApiError",
      status: 422,
    });
  });

  it("maps a 401 to a session-expired error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      putProfile(SESSION, PAYLOAD, fetchMock),
    ).rejects.toBeInstanceOf(ProfileApiError);
  });

  it("does not echo the request body into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await putProfile(SESSION, PAYLOAD, fetchMock);
      throw new Error("expected putProfile to throw");
    } catch (error) {
      const message = (error as ProfileApiError).message;
      expect(message).not.toContain("1.75");
      expect(message).not.toContain("1990");
    }
  });
});

describe("getProfile", () => {
  it("GETs the owner's profile with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(DTO));

    const result = await getProfile(SESSION, fetchMock);

    expect(result).toEqual(DTO);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/api/users/${SESSION.userId}/profile`);
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("maps a 404 to a ProfileApiError that fails closed", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(getProfile(SESSION, fetchMock)).rejects.toMatchObject({
      status: 404,
    });
  });
});
