/**
 * Tests for the FTY-196 label-proposal API client (consumed by FTY-197).
 *
 * Covers:
 * - getLabelProposal: reads `{ proposal }`, returns the item or null.
 * - getLabelProposal: correct GET endpoint + auth header.
 * - confirmLabelProposal: POSTs the adjustments body to the confirm endpoint.
 * - confirmLabelProposal: an empty adjustments object serializes to `{}`.
 * - Error responses map to nonjudgmental, value-free messages.
 */

import {
  confirmLabelProposal,
  getLabelProposal,
  LabelProposalApiError,
} from "./labelProposal";
import type { DerivedFoodItemDTO } from "./derivedItems";
import type { ApiSession } from "@/state/session";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

function proposalItem(): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: SESSION.userId,
    log_event_id: "event-1",
    name: "Granola bar",
    quantity_text: "1 serving",
    unit: "bar",
    amount: 1,
    status: "proposed",
    grams: 40,
    calories: 190,
    protein_g: 4,
    carbs_g: 29,
    fat_g: 7,
    calories_estimated: 190,
    protein_g_estimated: 4,
    carbs_g_estimated: 29,
    fat_g_estimated: 7,
    source: { source_type: "user_label", label: "Label scan", ref: "user_label" },
    is_edited: false,
    created_at: "2026-07-02T08:00:00Z",
    updated_at: "2026-07-02T08:00:00Z",
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("getLabelProposal", () => {
  it("reads the proposal item from the read shape", async () => {
    const item = proposalItem();
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ proposal: item }));

    const result = await getLabelProposal(SESSION, "event-1", fetchImpl);

    expect(result).toEqual(item);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      `${SESSION.baseUrl}/api/users/${SESSION.userId}/log-events/event-1/label-proposal`,
    );
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  it("returns null when the event has no uncounted proposal", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({ proposal: null }));
    const result = await getLabelProposal(SESSION, "event-1", fetchImpl);
    expect(result).toBeNull();
  });

  it("maps a 404 to a content-free message", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, 404));
    await expect(getLabelProposal(SESSION, "event-1", fetchImpl)).rejects.toBeInstanceOf(
      LabelProposalApiError,
    );
  });
});

describe("confirmLabelProposal", () => {
  it("POSTs an empty body when no adjustments are given", async () => {
    const item = proposalItem();
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ ...item, status: "resolved" }));

    const result = await confirmLabelProposal(SESSION, "event-1", {}, fetchImpl);

    expect(result.status).toBe("resolved");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      `${SESSION.baseUrl}/api/users/${SESSION.userId}/log-events/event-1/label-proposal/confirm`,
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
  });

  it("POSTs the supplied adjusted values", async () => {
    const item = proposalItem();
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ ...item, status: "resolved" }));

    await confirmLabelProposal(SESSION, "event-1", { calories: 250 }, fetchImpl);

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ calories: 250 });
  });

  it("maps a 422 to a value-free message", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(jsonResponse({}, 422));
    await expect(
      confirmLabelProposal(SESSION, "event-1", { calories: -1 }, fetchImpl),
    ).rejects.toBeInstanceOf(LabelProposalApiError);
  });
});
