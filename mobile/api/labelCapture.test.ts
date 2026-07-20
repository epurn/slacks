/**
 * Tests for the label-image upload API client (FTY-064; read fixed in FTY-381).
 *
 * Covers:
 * - Happy path: native file read → guard → raw-body upload → event returned.
 * - Save flag forwarded correctly in the query string (save=true / save=false).
 * - Correct endpoint, auth header, Content-Type, mimeType, and binary upload type.
 * - Client-side size guard rejects oversized files before the upload call.
 * - Client-side type guard rejects non-image content types before the upload call.
 * - An unreadable file is rejected content-free before any upload.
 * - API error responses mapped to nonjudgmental, content-free messages.
 * - Error messages never contain image bytes, URIs, or extracted content.
 */

// The native `File`/`UploadType` API is stubbed: these tests inject `openImage`,
// so `File` is never constructed — only `UploadType` needs a concrete value.
jest.mock("expo-file-system", () => ({
  File: class {},
  UploadType: { BINARY_CONTENT: 0, MULTIPART: 1 },
}));

import { UploadType } from "expo-file-system";

import {
  uploadLabelImage,
  validateImageGuard,
  MAX_UPLOAD_BYTES,
  ALLOWED_CONTENT_TYPES,
  LabelUploadApiError,
  LabelUploadTooLargeError,
  LabelUploadInvalidTypeError,
  LabelUploadUnreadableError,
  type LocalImageFile,
  type OpenLocalImage,
} from "./labelCapture";
import { setUnauthorizedHandler } from "./client";
import type { LogEventDTO } from "./logEvents";
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

const EVENT_DTO: LogEventDTO = {
  id: "label-event-1",
  user_id: SESSION.userId,
  raw_text: "nutrition label photo",
  name: null,
  status: "pending",
  created_at: "2026-06-27T10:00:00Z",
  updated_at: "2026-06-27T10:00:00Z",
};

/**
 * Build a fake local image file + its opener seam. `upload` is a jest mock so
 * tests can assert the URL/headers/body-type and whether it was called at all
 * (the size/type/exists guards must fire *before* any upload).
 */
function fakeImage(opts: {
  size?: number;
  type?: string;
  exists?: boolean;
  status?: number;
  body?: unknown;
  uploadRejects?: Error;
}): { openImage: OpenLocalImage; upload: jest.Mock; openMock: jest.Mock } {
  const {
    size = 50_000,
    type = "image/jpeg",
    exists = true,
    status = 201,
    body = EVENT_DTO,
    uploadRejects,
  } = opts;
  const upload = jest.fn(
    uploadRejects
      ? () => Promise.reject(uploadRejects)
      : () => Promise.resolve({ status, body: JSON.stringify(body) }),
  );
  const file: LocalImageFile = { exists, size, type, upload };
  const openMock = jest.fn().mockReturnValue(file);
  return { openImage: openMock as unknown as OpenLocalImage, upload, openMock };
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
  const LABEL_URL_BASE =
    "https://api.example.test/api/users/11111111-1111-1111-1111-111111111111/log-events/label";

  it("reads the local file, then streams the raw image to the label endpoint", async () => {
    const { openImage, upload, openMock } = fakeImage({ size: 50_000, type: "image/jpeg" });

    const result = await uploadLabelImage(SESSION, "file:///label.jpg", false, openImage);

    expect(result).toEqual(EVENT_DTO);

    // The local file is opened by URI, then uploaded exactly once.
    expect(openMock).toHaveBeenCalledWith("file:///label.jpg");
    expect(upload).toHaveBeenCalledTimes(1);

    const [uploadUrl, uploadOptions] = upload.mock.calls[0] as [
      string,
      {
        httpMethod: string;
        uploadType: UploadType;
        headers: Record<string, string>;
        mimeType: string;
      },
    ];
    expect(uploadUrl).toBe(`${LABEL_URL_BASE}?save=false`);
    expect(uploadOptions.httpMethod).toBe("POST");
    // Binary body (raw image bytes), not multipart — matches the contract wire shape.
    expect(uploadOptions.uploadType).toBe(UploadType.BINARY_CONTENT);
    expect(uploadOptions.headers.Authorization).toBe("Bearer test-token");
    expect(uploadOptions.headers["Content-Type"]).toBe("image/jpeg");
    expect(uploadOptions.mimeType).toBe("image/jpeg");
  });

  it("sends save=false in the query string when savePhoto is false", async () => {
    const { openImage, upload } = fakeImage({});
    await uploadLabelImage(SESSION, "file:///label.jpg", false, openImage);
    const [uploadUrl] = upload.mock.calls[0] as [string];
    expect(uploadUrl).toContain("?save=false");
  });

  it("sends save=true in the query string when savePhoto is true", async () => {
    const { openImage, upload } = fakeImage({});
    await uploadLabelImage(SESSION, "file:///label.jpg", true, openImage);
    const [uploadUrl] = upload.mock.calls[0] as [string];
    expect(uploadUrl).toContain("?save=true");
  });

  it("rejects an unreadable file content-free before any upload", async () => {
    const { openImage, upload } = fakeImage({ exists: false });

    await expect(
      uploadLabelImage(SESSION, "file:///gone.jpg", false, openImage),
    ).rejects.toBeInstanceOf(LabelUploadUnreadableError);

    // The guard fires before the network — no upload was attempted.
    expect(upload).not.toHaveBeenCalled();
  });

  it("rejects oversize images before the upload call (guard fires before network)", async () => {
    const { openImage, upload } = fakeImage({ size: MAX_UPLOAD_BYTES + 1 });

    await expect(
      uploadLabelImage(SESSION, "file:///huge.jpg", false, openImage),
    ).rejects.toThrow(LabelUploadTooLargeError);

    expect(upload).not.toHaveBeenCalled();
  });

  it("rejects non-image content types before the upload call", async () => {
    const { openImage, upload } = fakeImage({ type: "application/pdf" });

    await expect(
      uploadLabelImage(SESSION, "file:///doc.pdf", false, openImage),
    ).rejects.toThrow(LabelUploadInvalidTypeError);

    expect(upload).not.toHaveBeenCalled();
  });

  it("maps a 401 response to a session-expired message", async () => {
    const { openImage } = fakeImage({ status: 401, body: null });

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, openImage),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 401 });
  });

  it("invokes the unauthorized handler on a 401 before throwing", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const { openImage } = fakeImage({ status: 401, body: null });

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, openImage),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not invoke the unauthorized handler on a non-401 error", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const { openImage } = fakeImage({ status: 413, body: null });

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, openImage),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 413 });
    expect(handler).not.toHaveBeenCalled();
  });

  it("maps a 413 response to an oversized message", async () => {
    const { openImage } = fakeImage({ status: 413, body: null });

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, openImage),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 413 });
  });

  it("maps a 503 (retryable transient) to a reassuring, transient-framed message", async () => {
    const { openImage } = fakeImage({ status: 503, body: null });

    let caught: LabelUploadApiError | undefined;
    try {
      await uploadLabelImage(SESSION, "file:///label.jpg", false, openImage);
    } catch (err) {
      caught = err as LabelUploadApiError;
    }

    expect(caught).toBeInstanceOf(LabelUploadApiError);
    expect(caught?.status).toBe(503);
    expect(caught?.message).toBe(
      "The label service is busy right now. Please try again in a moment.",
    );
    // Reads as temporary + retryable, not permanent/user-caused.
    expect(caught?.message).toMatch(/try again/i);
  });

  it("the 503 message leaks no raw status code, image path, bytes, or extracted content", async () => {
    const sensitiveUri = "file:///private/nutrition-secret.jpg";
    const { openImage } = fakeImage({ status: 503, body: null });

    let message = "";
    try {
      await uploadLabelImage(SESSION, sensitiveUri, false, openImage);
    } catch (err) {
      message = (err as LabelUploadApiError).message;
    }

    // No raw HTTP status number (no digits at all) and no "status" echo token.
    expect(message).not.toMatch(/\d/);
    expect(message).not.toMatch(/status/i);
    // No image path/bytes/extracted content.
    expect(message).not.toContain(sensitiveUri);
    expect(message).not.toContain("private");
    expect(message).not.toContain("nutrition-secret");
    expect(message).not.toMatch(/byte|base64|data:/);
  });

  it("does not invoke the unauthorized handler on a 503 error", async () => {
    const handler = jest.fn();
    setUnauthorizedHandler(handler);
    const { openImage } = fakeImage({ status: 503, body: null });

    await expect(
      uploadLabelImage(SESSION, "file:///label.jpg", false, openImage),
    ).rejects.toMatchObject({ name: "LabelUploadApiError", status: 503 });
    expect(handler).not.toHaveBeenCalled();
  });

  it("keeps the 401/413/generic messages unchanged (503 case added no regressions)", async () => {
    const cases: { status: number; message: string }[] = [
      { status: 401, message: "Your session has expired. Sign in again to keep logging." },
      { status: 413, message: "That photo is too large to upload." },
      { status: 500, message: "We couldn’t upload the label (status 500)." },
    ];

    for (const { status, message } of cases) {
      const { openImage } = fakeImage({ status, body: null });
      let caught: LabelUploadApiError | undefined;
      try {
        await uploadLabelImage(SESSION, "file:///label.jpg", false, openImage);
      } catch (err) {
        caught = err as LabelUploadApiError;
      }
      expect(caught?.status).toBe(status);
      expect(caught?.message).toBe(message);
    }
  });

  it("error messages do not contain image bytes, URIs, or extracted content", async () => {
    const sensitiveUri = "file:///private/nutrition-secret.jpg";
    const { openImage } = fakeImage({ status: 500, body: null });

    try {
      await uploadLabelImage(SESSION, sensitiveUri, false, openImage);
      throw new Error("expected uploadLabelImage to throw");
    } catch (err) {
      const message = (err as LabelUploadApiError).message;
      expect(message).not.toContain(sensitiveUri);
      expect(message).not.toContain("private");
      expect(message).not.toContain("nutrition-secret");
      expect(message).not.toMatch(/byte|base64|data:/);
    }
  });

  it("falls back to image/jpeg when the file reports an empty type", async () => {
    const { openImage, upload } = fakeImage({ type: "" }); // empty type

    const result = await uploadLabelImage(SESSION, "file:///label.jpg", false, openImage);
    expect(result).toEqual(EVENT_DTO);

    const [, uploadOptions] = upload.mock.calls[0] as [
      string,
      { headers: Record<string, string>; mimeType: string },
    ];
    expect(uploadOptions.headers["Content-Type"]).toBe("image/jpeg");
    expect(uploadOptions.mimeType).toBe("image/jpeg");
  });
});
