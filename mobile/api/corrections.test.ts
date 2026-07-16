/**
 * FTY-366: corrections client tests — request construction and per-flow error
 * copy for the re-match operations (`listSourceCandidates` / `reResolveItem`).
 *
 * The re-resolve `422` mapping is the load-bearing behaviour: the route's two
 * documented application-level codes (`source_not_resolvable`,
 * `needs_clarification` — evidence-retrieval.md → Item Re-match → Errors) map
 * to distinct, honest messages, and no re-resolve error ever tells the user to
 * "check the value" (there is no user-entered value on a re-resolve). All
 * fixtures are opaque refs — no nutrition values, candidate names, or queries
 * appear in any error path.
 */

import type { ApiSession } from "@/api/client";
import {
  CorrectionsApiError,
  listSourceCandidates,
  reResolveItem,
  type SourceCandidate,
} from "@/api/corrections";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const ITEM_ID = "44444444-4444-4444-4444-444444444444";

const CANDIDATE: SourceCandidate = {
  source_type: "trusted_nutrition_database",
  source_ref: "usda_fdc:2345170",
  name: "Candidate A",
  basis: "per_100g",
  calories: 192,
  protein_g: 10,
  carbs_g: 17,
  fat_g: 9,
};

function okResponse(body: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    json: async () => body,
  } as unknown as Response;
}

function errorResponse(status: number, body: unknown): Response {
  return {
    ok: false,
    status,
    json: async () => body,
  } as unknown as Response;
}

async function messageOf(promise: Promise<unknown>): Promise<string> {
  try {
    await promise;
  } catch (err) {
    expect(err).toBeInstanceOf(CorrectionsApiError);
    return (err as CorrectionsApiError).message;
  }
  throw new Error("expected the call to reject");
}

describe("listSourceCandidates", () => {
  it("POSTs an empty JSON object when no query override is given", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ candidates: [CANDIDATE] }));

    const result = await listSourceCandidates(
      SESSION,
      ITEM_ID,
      undefined,
      fetchMock as unknown as typeof fetch,
    );

    expect(result).toEqual([CANDIDATE]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `https://api.example.test/api/users/${SESSION.userId}/derived-items/food/${ITEM_ID}/source-candidates`,
    );
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({});
  });

  it("POSTs the query override as the only body field", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(okResponse({ candidates: [] }));

    await listSourceCandidates(
      SESSION,
      ITEM_ID,
      "turkey",
      fetchMock as unknown as typeof fetch,
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ query: "turkey" });
  });

  it("keeps the existing correction copy on a 422", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(422, {
        detail: [
          {
            type: "string_too_long",
            loc: ["body", "query"],
            msg: "String should have at most 256 characters",
          },
        ],
      }),
    );

    const message = await messageOf(
      listSourceCandidates(
        SESSION,
        ITEM_ID,
        "q",
        fetchMock as unknown as typeof fetch,
      ),
    );

    expect(message).toBe(
      "That correction couldn't be applied. Check the value and try again.",
    );
  });

  it("maps a 503 to the retryable alternatives message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(503, { detail: { error: "alternatives_unavailable" } }),
    );

    const message = await messageOf(
      listSourceCandidates(
        SESSION,
        ITEM_ID,
        undefined,
        fetchMock as unknown as typeof fetch,
      ),
    );

    expect(message).toBe(
      "Alternatives are temporarily unavailable. Try again in a moment.",
    );
  });
});

describe("reResolveItem", () => {
  it("POSTs exactly { source_ref } to the re-resolve endpoint", async () => {
    const updated = { item_type: "food", id: ITEM_ID };
    const fetchMock = jest.fn().mockResolvedValue(okResponse(updated));

    const result = await reResolveItem(
      SESSION,
      ITEM_ID,
      CANDIDATE.source_ref,
      fetchMock as unknown as typeof fetch,
    );

    expect(result).toEqual(updated);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `https://api.example.test/api/users/${SESSION.userId}/derived-items/food/${ITEM_ID}/re-resolve`,
    );
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({
      source_ref: "usda_fdc:2345170",
    });
  });

  it("maps a source_not_resolvable 422 to the pick-another-match message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(422, { detail: { error: "source_not_resolvable" } }),
    );

    const message = await messageOf(
      reResolveItem(
        SESSION,
        ITEM_ID,
        CANDIDATE.source_ref,
        fetchMock as unknown as typeof fetch,
      ),
    );

    expect(message).toBe(
      "That match couldn't be applied. Pick a different match or search again.",
    );
  });

  it("maps a needs_clarification 422 to the how-much follow-up message", async () => {
    // The reproduced FTY-366 dogfood failure: the chosen source cannot cost the
    // item's current quantity, so the server asks for an amount — the client
    // invites that follow-up instead of a dead generic error.
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(422, {
        detail: {
          error: "needs_clarification",
          question:
            "How much did you have (for example, in grams, millilitres, or servings)?",
        },
      }),
    );

    const message = await messageOf(
      reResolveItem(
        SESSION,
        ITEM_ID,
        CANDIDATE.source_ref,
        fetchMock as unknown as typeof fetch,
      ),
    );

    expect(message).toBe(
      "That match needs to know how much you had. Update the amount, then try the match again.",
    );
  });

  it("maps a request-validation 422 (array detail) to the plain residual message", async () => {
    const fetchMock = jest.fn().mockResolvedValue(
      errorResponse(422, {
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "source_ref"],
            msg: "String should have at least 1 character",
          },
        ],
      }),
    );

    const message = await messageOf(
      reResolveItem(SESSION, ITEM_ID, "", fetchMock as unknown as typeof fetch),
    );

    expect(message).toBe("That match couldn't be applied. Try again.");
  });

  it("never uses check-the-value language on any re-resolve 422", async () => {
    const bodies = [
      { detail: { error: "source_not_resolvable" } },
      { detail: { error: "needs_clarification", question: "?" } },
      { detail: { error: "some_future_code" } },
      { detail: [{ type: "extra_forbidden", loc: ["body", "x"] }] },
      "not json at all",
    ];
    for (const body of bodies) {
      const fetchMock = jest.fn().mockResolvedValue(errorResponse(422, body));
      const message = await messageOf(
        reResolveItem(
          SESSION,
          ITEM_ID,
          CANDIDATE.source_ref,
          fetchMock as unknown as typeof fetch,
        ),
      );
      expect(message.toLowerCase()).not.toContain("check the value");
    }
  });

  it("keeps the shared non-422 messages (404 shown here)", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue(errorResponse(404, { detail: "derived item not found" }));

    const message = await messageOf(
      reResolveItem(
        SESSION,
        ITEM_ID,
        CANDIDATE.source_ref,
        fetchMock as unknown as typeof fetch,
      ),
    );

    expect(message).toBe("We couldn't find that item.");
  });
});
