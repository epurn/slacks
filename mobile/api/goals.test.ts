import {
  GoalsApiError,
  createGoal,
  getActiveGoalDirection,
  getTarget,
  resetTargetOverride,
  setTargetOverride,
  type GoalTargetResponse,
  type GoalsSession,
} from "./goals";
import type { TargetReadModel } from "./dailySummary";

const SESSION: GoalsSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  // A user id with a character that must be percent-encoded in the path.
  userId: "user/with space",
};

const ENCODED_BASE =
  "https://api.example.test/api/users/user%2Fwith%20space";

const TARGET: TargetReadModel = {
  calories: { effective: 2000, derived: 2100, source: "user" },
  protein_g: { effective: 150, derived: 150, source: "derived" },
  carbs_g: { effective: 200, derived: 200, source: "derived" },
  fat_g: { effective: 60, derived: 70, source: "user" },
};

const GOAL_RESPONSE: GoalTargetResponse = {
  goal: {
    id: "22222222-2222-2222-2222-222222222222",
    user_id: "user/with space",
    start_weight_kg: 80,
    start_date: "2026-06-28",
    target_weight_kg: 75,
    target_date: "2026-09-28",
    is_active: true,
  },
  target: {
    calories: 1900,
    rmr_kcal: 1600,
    tdee_kcal: 2200,
    direction: "loss",
    clamped: false,
  },
  provenance: { source: "derived", basis: "goal_and_metrics" },
  clamp: { clamped: false, reason: null },
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

describe("createGoal", () => {
  it("POSTs the goal payload to the percent-encoded goal URL with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(GOAL_RESPONSE, 201));

    const result = await createGoal(
      SESSION,
      { direction: "loss", pace: "steady" },
      fetchMock,
    );

    expect(result).toEqual(GOAL_RESPONSE);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ENCODED_BASE}/goal`);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
    expect(JSON.parse(init.body as string)).toEqual({
      direction: "loss",
      pace: "steady",
    });
  });

  it("maps a 409 to a 'complete your profile' GoalsApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(409));
    await expect(
      createGoal(SESSION, { direction: "loss", pace: "steady" }, fetchMock),
    ).rejects.toMatchObject({
      name: "GoalsApiError",
      status: 409,
      message: "Complete your profile before setting a goal.",
    });
  });

  it("maps a 401 to a session-expired GoalsApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      createGoal(SESSION, { direction: "maintain" }, fetchMock),
    ).rejects.toMatchObject({ status: 401 });
  });
});

describe("getTarget", () => {
  it("GETs the target read-model with a bearer token", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(TARGET));

    const result = await getTarget(SESSION, fetchMock);

    expect(result).toEqual(TARGET);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ENCODED_BASE}/target`);
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("maps a 404 to a GoalsApiError that fails closed", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(getTarget(SESSION, fetchMock)).rejects.toBeInstanceOf(
      GoalsApiError,
    );
  });
});

describe("getActiveGoalDirection", () => {
  it("GETs the goal read model and returns its direction", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse({ direction: "gain" }));

    const result = await getActiveGoalDirection(SESSION, fetchMock);

    expect(result).toBe("gain");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ENCODED_BASE}/goal`);
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer test-token",
    );
  });

  it("maps a 404 (no active goal / fail-closed) to null, not an error", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(404));
    await expect(getActiveGoalDirection(SESSION, fetchMock)).resolves.toBeNull();
  });

  it("still throws a GoalsApiError on a non-404 failure (e.g. 401)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      getActiveGoalDirection(SESSION, fetchMock),
    ).rejects.toMatchObject({ name: "GoalsApiError", status: 401 });
  });
});

describe("setTargetOverride", () => {
  it("PUTs the override payload to the override URL and returns the read-model", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(TARGET));

    const result = await setTargetOverride(
      SESSION,
      { calorie_target_kcal: 1800 },
      fetchMock,
    );

    expect(result).toEqual(TARGET);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ENCODED_BASE}/target/override`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      calorie_target_kcal: 1800,
    });
  });

  it("maps a 422 out-of-band value to a GoalsApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    await expect(
      setTargetOverride(SESSION, { calorie_target_kcal: 99999 }, fetchMock),
    ).rejects.toMatchObject({ name: "GoalsApiError", status: 422 });
  });

  it("never echoes the submitted override value into the error message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(422));
    try {
      await setTargetOverride(SESSION, { calorie_target_kcal: 99999 }, fetchMock);
      throw new Error("expected setTargetOverride to throw");
    } catch (error) {
      expect((error as GoalsApiError).message).not.toContain("99999");
    }
  });
});

describe("resetTargetOverride", () => {
  it("POSTs the named targets to the reset URL", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(TARGET));

    const result = await resetTargetOverride(SESSION, ["calories", "fat"], fetchMock);

    expect(result).toEqual(TARGET);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ENCODED_BASE}/target/override/reset`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      targets: ["calories", "fat"],
    });
  });

  it("sends an empty object when no targets are passed (reset all)", async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(TARGET));

    await resetTargetOverride(SESSION, undefined, fetchMock);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it("maps a 401 to a GoalsApiError", async () => {
    const fetchMock = jest.fn().mockResolvedValue(errorResponse(401));
    await expect(
      resetTargetOverride(SESSION, undefined, fetchMock),
    ).rejects.toBeInstanceOf(GoalsApiError);
  });
});
