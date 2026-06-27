/**
 * Tests for the label-image upload API client (FTY-064).
 *
 * Covers:
 * - Happy path: local file read → guard → raw-body POST → event returned.
 * - Save flag forwarded correctly in the query string (save=true / save=false).
 * - Correct endpoint, auth header, Content-Type, and raw-image body.
 * - Client-side size guard rejects oversized files before the upload call.
 * - Client-side type guard rejects non-image content types before the upload call.
 * - API error responses mapped to nonjudgmental, content-free messages.
 * - Error messages never contain image bytes, URIs, or extracted content.
 */

import {
  uploadLabelImage,
  validateImageGuard,
  MAX_UPLOAD_BYTES,
  ALLOWED_CONTENT_TYPES,
  LabelUploadApiError,
  LabelUploadTooLargeError,
  LabelUploadInvalidTypeError,
} from "./labelCapture";
import type { LogEventDTO } from "./logEvents";
import type { ApiSession } from "@/state/session";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const EVENT_DTO: LogEventDTO = {
  id: "label-event-1",
  user_id: SESSION.userId,
  raw_text: "nutrition label photo",
  status: "pending",
  created_at: "2026-06-27T10:00:00Z",
  updated_at: "2026-06-27T10:00:00Z",
};

// A small mock blob of known size and type.
function makeBlobResponse(sizeBytes: number, contentType: string): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => ({ size: sizeBytes, type: contentType }),
  } as unknown as Response;
}

function makeUploadResponse(body: unknown, status = 201): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

// ─── validateImageGuard (pure) ────────────────────────────────────────────────

describe("validateImageGuard", () => {
  it("exports MAX_UPLOAD_BYTES as 10 MiB", () => {
    expect(MAX_UPLOAD_BYTES).toBe(10 * 1024 * 1024);
  });

  it("ALLOWED_CONTENT_TYPES includes jpeg, png, webp", () => {
    expect(ALLOWED_CONTENT_TYPES.has("image/jpeg")).toBe(true);
    expect(ALLOWED_CONTENT_TYPES.has("image/png")).toBe(true);
    expect(ALLOWED_CONTENT_TYPES.has("image/webp")).toBe(true);
  });

  it("allows exactly MAX_UPLOAD_BYTES", () => {
    expect(() => validateImageGuard(MAX_UPLOAD_BYTES, "image/jpeg")).not.toThrow();
  });

  it("throws LabelUploadTooLargeError above the limit", () => {
    expect(() => validateImageGuard(MAX_UPLOAD_BYTES + 1, "image/jpeg")).toThrow(
      LabelUploadTooLargeError,
    );
  });

  it("throws LabelUploadInvalidTypeError for non-image types", () => {
    expect(() => validateImageGuard(1000, "text/html")).toThrow(LabelUploadInvalidTypeError);
    expect(() => validateImageGuard(1000, "application/octet-stream")).toThrow(
      LabelUploadInvalidTypeError,
    );
  });

  it("strips content-type parameters before checking", () => {
    expect(() => validateImageGuard(1000, "image/jpeg; charset=utf-8")).not.toThrow();
  });
});

// ─── uploadLabelImage ─────────────────────────────────────────────────────────

describe("uploadLabelImage", () => {
  it("fetches the local file, then POSTs the raw image to the label endpoint", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(50_000, "image/jpeg")) // local file
      .mockResolvedValueOnce(makeUploadResponse(EVENT_DTO, 201));     // upload

    const result = await uploadLabelImage(SESSION, "file:///label.jpg", false, fetchMock);

    expect(result).toEqual(EVENT_DTO);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // First call: reads the local image file.
    const [localUri] = fetchMock.mock.calls[0] as [string];
    expect(localUri).toBe("file:///label.jpg");

    // Second call: the raw-body upload (save flag in the query string).
    const [uploadUrl, uploadInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(uploadUrl).toBe(
      "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/label?save=false",
    );
    expect(uploadInit.method).toBe("POST");
    const headers = uploadInit.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token");
    // The header declares the image type; the body is the raw image blob.
    expect(headers["Content-Type"]).toBe("image/jpeg");
    expect((uploadInit.body as { size: number }).size).toBe(50_000);
  });

  it("sends save=false in the query string when savePhoto is false", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(makeUploadResponse(EVENT_DTO, 201));

    await uploadLabelImage(SESSION, "file:///label.jpg", false, fetchMock);

    const [uploadUrl] = fetchMock.mock.calls[1] as [string];
    expect(uploadUrl).toContain("?save=false");
  });

  it("sends save=true in the query string when savePhoto is true", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(makeUploadResponse(EVENT_DTO, 201));

    await uploadLabelImage(SESSION, "file:///label.jpg", true, fetchMock);

    const [uploadUrl] = fetchMock.mock.calls[1] as [string];
    expect(uploadUrl).toContain("?save=true");
  });

  it("rejects oversize images before the upload call (guard fires before network)", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(MAX_UPLOAD_BYTES + 1, "image/jpeg"));

    await expect(
      uploadLabelImage(SESSION, "file:///huge.jpg", false, fetchMock),
    ).rejects.toThrow(LabelUploadTooLargeError);

    // Only one fetch call (the local file read); the upload was never attempted.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects non-image content types before the upload call", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "application/pdf"));

    await expect(
      uploadLabelImage(SESSION, "file:///doc.pdf", false, fetchMock),
    ).rejects.toThrow(LabelUploadInvalidTypeError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("maps a 401 response to a session-expired message", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(makeUploadResponse(null, 401));

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, fetchMock),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 401 });
  });

  it("maps a 413 response to an oversized message", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(makeUploadResponse(null, 413));

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, fetchMock),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 413 });
  });

  it("error messages do not contain image bytes, URIs, or extracted content", async () => {
    const sensitiveUri = "file:///private/nutrition-secret.jpg";
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "image/jpeg"))
      .mockResolvedValueOnce(makeUploadResponse(null, 500));

    try {
      await uploadLabelImage(SESSION, sensitiveUri, false, fetchMock);
      throw new Error("expected uploadLabelImage to throw");
    } catch (err) {
      const message = (err as LabelUploadApiError).message;
      expect(message).not.toContain(sensitiveUri);
      expect(message).not.toContain("private");
      expect(message).not.toContain("nutrition-secret");
      expect(message).not.toMatch(/byte|base64|data:/);
    }
  });

  it("falls back to image/jpeg when the blob has an empty type", async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(makeBlobResponse(1000, "")) // empty type
      .mockResolvedValueOnce(makeUploadResponse(EVENT_DTO, 201));

    const result = await uploadLabelImage(SESSION, "file:///label.jpg", false, fetchMock);
    expect(result).toEqual(EVENT_DTO);
  });
});
