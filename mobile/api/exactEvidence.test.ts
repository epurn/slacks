/**
 * Tests for the exact-evidence proposal API client (FTY-306 / FTY-310).
 *
 * Covers:
 * - Barcode proposal: item-scoped URL, auth header, and `{ barcode }`-only body.
 * - Barcode trim / non-empty guard fires before any network call.
 * - Label proposal: shared size/type guard before network, raw-body POST with the
 *   declared Content-Type and the `save` query flag, and 401 → unauthorized
 *   notifier.
 * - Apply: sends `{ proposal_ref, amount? }` only, never calories/macros, and
 *   returns the updated DerivedFoodItemDTO.
 * - Typed proposal outcomes distinguish exact / fallback / none.
 * - Error mapping is content-free (no barcode, image URI, or nutrition values) and
 *   maps the documented statuses.
 */

import {
  requestBarcodeExactEvidenceProposal,
  uploadLabelExactEvidenceProposal,
  applyExactEvidenceProposal,
  ExactEvidenceApiError,
  ExactEvidenceEmptyBarcodeError,
} from "./exactEvidence";
import type {
  ExactEvidenceProposal,
  ExactEvidenceProposalKind,
  ExactEvidenceProposalQuality,
  ExactEvidenceProposalPreview,
  ExactEvidenceExactProposal,
  ExactEvidenceFallbackProposal,
  ExactEvidenceNoneProposal,
} from "./exactEvidence";
import { setUnauthorizedHandler } from "./client";
import { LabelUploadTooLargeError, LabelUploadInvalidTypeError } from "./labelCapture";
import type { DerivedFoodItemDTO } from "./derivedItems";
import type { ApiSession } from "@/state/session";

// The unauthorized handler is a module-level singleton; restore the safe no-op
// after each test so a registered spy can't leak into another test.
afterEach(() => {
  setUnauthorizedHandler(null);
});

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const ITEM_ID = "food-item-1";
const ITEM_BASE = `https://api.example.test/api/users/${SESSION.userId}/derived-items/food/${ITEM_ID}/exact-upgrade`;

const EXACT_PREVIEW: ExactEvidenceProposalPreview = {
  source: {
    source_type: "product_database",
    label: "Open Food Facts",
    ref: "open_food_facts:0123456789012",
  },
  calories: 210,
  protein_g: 5,
  carbs_g: 30,
  fat_g: 8,
  amount: 1,
  serving_label: "1 serving",
};

const EXACT_PROPOSAL: ExactEvidenceExactProposal = {
  proposal_ref: "prop-abc",
  kind: "barcode",
  quality: "exact",
  failure_reason: null,
  can_cost_current_amount: true,
  preview: EXACT_PREVIEW,
};

const FALLBACK_PROPOSAL: ExactEvidenceFallbackProposal = {
  proposal_ref: "prop-def",
  kind: "label",
  quality: "fallback",
  failure_reason: "label_unreadable",
  can_cost_current_amount: false,
  preview: {
    source: { source_type: "model_prior", label: "Rough estimate", ref: "model_prior" },
    calories: 180,
    protein_g: null,
    carbs_g: null,
    fat_g: null,
    amount: 1,
    serving_label: null,
  },
};

const NONE_PROPOSAL: ExactEvidenceNoneProposal = {
  proposal_ref: "prop-ghi",
  kind: "barcode",
  quality: "none",
  failure_reason: "barcode_no_match",
  can_cost_current_amount: false,
  preview: null,
};

const UPDATED_ITEM: DerivedFoodItemDTO = {
  item_type: "food",
  id: ITEM_ID,
  user_id: SESSION.userId,
  log_event_id: "event-1",
  name: "Granola bar",
  quantity_text: "1 bar",
  unit: null,
  amount: 1,
  status: "resolved",
  grams: 40,
  calories: 210,
  protein_g: 5,
  carbs_g: 30,
  fat_g: 8,
  calories_estimated: 210,
  protein_g_estimated: 5,
  carbs_g_estimated: 30,
  fat_g_estimated: 8,
  created_at: "2026-07-10T10:00:00Z",
  updated_at: "2026-07-10T10:05:00Z",
  source: {
    source_type: "product_database",
    label: "Open Food Facts",
    ref: "open_food_facts:0123456789012",
  },
  is_edited: false,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function makeBlobResponse(sizeBytes: number, contentType: string): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => ({ size: sizeBytes, type: contentType }),
  } as unknown as Response;
}

// ─── wire type surface ───────────────────────────────────────────────────────

describe("exact-evidence wire types", () => {
  it("enumerates the proposal kind and quality wire values", () => {
    const kinds: ExactEvidenceProposalKind[] = ["barcode", "label"];
    const qualities: ExactEvidenceProposalQuality[] = ["exact", "fallback", "none"];
    // Each fixture's discriminants are members of the published wire enums.
    expect(kinds).toContain(EXACT_PROPOSAL.kind);
    expect(kinds).toContain(FALLBACK_PROPOSAL.kind);
    expect(qualities).toContain(EXACT_PROPOSAL.quality);
    expect(qualities).toContain(FALLBACK_PROPOSAL.quality);
    expect(qualities).toContain(NONE_PROPOSAL.quality);
  });
});

// ─── requestBarcodeExactEvidenceProposal ─────────────────────────────────────

describe("requestBarcodeExactEvidenceProposal", () => {
  it("POSTs the item-scoped barcode URL with auth header and barcode-only body", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(EXACT_PROPOSAL, 200));

    const result = await requestBarcodeExactEvidenceProposal(
      SESSION,
      ITEM_ID,
      "0123456789012",
      fetchMock,
    );

    expect(result).toEqual(EXACT_PROPOSAL);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ITEM_BASE}/barcode`);
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("application/json");
    // Body carries ONLY the barcode — no nutrition facts, no other candidate fields.
    expect(JSON.parse(init.body as string)).toEqual({ barcode: "0123456789012" });
  });

  it("trims surrounding whitespace from the barcode before sending", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(EXACT_PROPOSAL, 200));

    await requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, "  0123456789012  ", fetchMock);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ barcode: "0123456789012" });
  });

  it("rejects an empty / whitespace-only barcode before any network call", async () => {
    const fetchMock = jest.fn();

    await expect(
      requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, "   ", fetchMock),
    ).rejects.toThrow(ExactEvidenceEmptyBarcodeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns a fallback proposal with its true low-trust provenance", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(FALLBACK_PROPOSAL, 200));

    const result = await requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, "999", fetchMock);

    // The union narrows on `quality`; a fallback keeps a rough source, never exact.
    expect(result.quality).toBe("fallback");
    if (result.quality === "fallback") {
      expect(result.preview.source.source_type).toBe("model_prior");
      expect(result.failure_reason).toBe("label_unreadable");
    }
  });

  it("returns a none proposal (null preview, required failure_reason)", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(NONE_PROPOSAL, 200));

    const result: ExactEvidenceProposal = await requestBarcodeExactEvidenceProposal(
      SESSION,
      ITEM_ID,
      "000",
      fetchMock,
    );

    expect(result.quality).toBe("none");
    if (result.quality === "none") {
      expect(result.preview).toBeNull();
      expect(result.failure_reason).toBe("barcode_no_match");
    }
  });

  it("maps a 404 to a content-free 'find that item' message", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(null, 404));

    await expect(
      requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, "0123456789012", fetchMock),
    ).rejects.toMatchObject({ name: "ExactEvidenceApiError", status: 404 });
  });

  it("maps a 503 to a temporary-unavailable message and never echoes the barcode", async () => {
    const secretBarcode = "0123456789012";
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(null, 503));

    try {
      await requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, secretBarcode, fetchMock);
      throw new Error("expected a throw");
    } catch (err) {
      expect((err as ExactEvidenceApiError).status).toBe(503);
      expect((err as ExactEvidenceApiError).message).not.toContain(secretBarcode);
    }
  });

  it("invokes the unauthorized handler on a 401", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(null, 401));

    await expect(
      requestBarcodeExactEvidenceProposal(SESSION, ITEM_ID, "0123456789012", fetchMock),
    ).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

// ─── uploadLabelExactEvidenceProposal ────────────────────────────────────────

describe("uploadLabelExactEvidenceProposal", () => {
  it("guards, then POSTs raw bytes to the label URL with save flag and Content-Type", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(50_000, "image/jpeg")) // local file read
      .mockResolvedValueOnce(jsonResponse(EXACT_PROPOSAL, 200)); // upload

    const result = await uploadLabelExactEvidenceProposal(
      SESSION,
      ITEM_ID,
      "file:///label.jpg",
      true,
      fetchMock,
    );

    expect(result).toEqual(EXACT_PROPOSAL);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [localUri] = fetchMock.mock.calls[0] as [string];
    expect(localUri).toBe("file:///label.jpg");

    const [uploadUrl, uploadInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(uploadUrl).toBe(`${ITEM_BASE}/label?save=true`);
    expect(uploadInit.method).toBe("POST");
    const headers = uploadInit.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    expect(headers["Content-Type"]).toBe("image/jpeg");
    expect((uploadInit.body as { size: number }).size).toBe(50_000);
  });

  it("sends save=false when savePhoto is false", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(jsonResponse(EXACT_PROPOSAL, 200));

    await uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, "file:///label.jpg", false, fetchMock);

    const [uploadUrl] = fetchMock.mock.calls[1] as [string];
    expect(uploadUrl).toContain("?save=false");
  });

  it("rejects oversize images before the upload call (shared guard fires first)", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(11 * 1024 * 1024, "image/jpeg"));

    await expect(
      uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, "file:///huge.jpg", false, fetchMock),
    ).rejects.toThrow(LabelUploadTooLargeError);
    // Only the local file read happened; the upload was never attempted.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects non-image content types before the upload call", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "application/pdf"));

    await expect(
      uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, "file:///doc.pdf", false, fetchMock),
    ).rejects.toThrow(LabelUploadInvalidTypeError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears the session on a 401 (invokes the unauthorized handler before throwing)", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(jsonResponse(null, 401));

    await expect(
      uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, "file:///label.jpg", false, fetchMock),
    ).rejects.toMatchObject({ name: "ExactEvidenceApiError", status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not invoke the unauthorized handler on a non-401 error", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(jsonResponse(null, 413));

    await expect(
      uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, "file:///label.jpg", false, fetchMock),
    ).rejects.toMatchObject({ status: 413 });
    expect(handler).not.toHaveBeenCalled();
  });

  it("error messages never contain the image URI or extracted content", async () => {
    const sensitiveUri = "file:///private/label-secret.jpg";
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(jsonResponse(null, 500));

    try {
      await uploadLabelExactEvidenceProposal(SESSION, ITEM_ID, sensitiveUri, false, fetchMock);
      throw new Error("expected a throw");
    } catch (err) {
      const message = (err as ExactEvidenceApiError).message;
      expect(message).not.toContain(sensitiveUri);
      expect(message).not.toContain("private");
      expect(message).not.toContain("label-secret");
      expect(message).not.toMatch(/byte|base64|data:/);
    }
  });
});

// ─── applyExactEvidenceProposal ──────────────────────────────────────────────

describe("applyExactEvidenceProposal", () => {
  it("POSTs proposal_ref only (no amount) and returns the updated item", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(UPDATED_ITEM, 200));

    const result = await applyExactEvidenceProposal(SESSION, ITEM_ID, "prop-abc", undefined, fetchMock);

    expect(result).toEqual(UPDATED_ITEM);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${ITEM_BASE}/apply`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ proposal_ref: "prop-abc" });
  });

  it("includes the optional amount when supplied", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(UPDATED_ITEM, 200));

    await applyExactEvidenceProposal(SESSION, ITEM_ID, "prop-abc", 2, fetchMock);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ proposal_ref: "prop-abc", amount: 2 });
  });

  it("never smuggles nutrition facts into the apply body", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(UPDATED_ITEM, 200));

    await applyExactEvidenceProposal(SESSION, ITEM_ID, "prop-abc", 3, fetchMock);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    // Only the opaque ref and amount cross the wire — no calories/macros channel.
    expect(Object.keys(body).sort()).toEqual(["amount", "proposal_ref"]);
    expect(body).not.toHaveProperty("calories");
    expect(body).not.toHaveProperty("protein_g");
    expect(body).not.toHaveProperty("carbs_g");
    expect(body).not.toHaveProperty("fat_g");
  });

  it("maps a 422 (unresolvable ref / amount_required) to content-free copy", async () => {
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse({ error: "amount_required" }, 422));

    await expect(
      applyExactEvidenceProposal(SESSION, ITEM_ID, "prop-abc", undefined, fetchMock),
    ).rejects.toMatchObject({ name: "ExactEvidenceApiError", status: 422 });
  });

  it("invokes the unauthorized handler on a 401", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const fetchMock = jest.fn().mockResolvedValueOnce(jsonResponse(null, 401));

    await expect(
      applyExactEvidenceProposal(SESSION, ITEM_ID, "prop-abc", undefined, fetchMock),
    ).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
