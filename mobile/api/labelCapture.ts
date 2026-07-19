/**
 * Nutrition-label image upload client (FTY-064; on-device read fixed in FTY-381).
 *
 * Sends a captured label photo to the label-upload endpoint defined by
 * `docs/contracts/label-upload.md`: the raw image bytes are the request body, the
 * `Content-Type` header declares the image type, and a `save` query flag carries
 * the FTY-077 retention choice. The backend validates the image as data, runs the
 * FTY-061 extraction pipeline in-request, and returns the resulting log event. A
 * client-side guard rejects oversize or wrong-type payloads before any network
 * call — the authoritative trust boundary is the backend.
 *
 * FTY-381: the file read + upload go through `expo-file-system`'s `File` (the
 * repo-standard on-device file API), not `fetch(file://).blob()`. The old blob
 * path was fragile in React Native / Expo Go — reading a local `file://` URI and
 * calling `.blob()` could throw or hang **before** the upload POST ever fired,
 * which is exactly why zero label uploads ever reached the backend. `File.upload`
 * streams the raw bytes from disk through native networking, bypassing the JS
 * blob machinery entirely.
 *
 * Privacy: errors carry only HTTP status and a fixed action description —
 * never image bytes, file paths, URIs, or extracted content. Nothing is logged.
 */

import { File, UploadType } from "expo-file-system";

import { ApiError, notifyUnauthorized } from "@/api/client";
import type { ApiSession } from "@/api/client";
import type { LogEventDTO } from "@/api/logEvents";

/** Maximum accepted upload size in bytes (10 MiB). Mirrors backend MAX_ATTACHMENT_BYTES. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** Allowed image content types. Mirrors backend ALLOWED_CONTENT_TYPES. */
export const ALLOWED_CONTENT_TYPES: ReadonlySet<string> = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

/** Raised when the backend label endpoint returns a non-2xx status. */
export class LabelUploadApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "LabelUploadApiError";
  }
}

/** Raised client-side when the image exceeds MAX_UPLOAD_BYTES. */
export class LabelUploadTooLargeError extends Error {
  constructor() {
    super("This photo is too large to upload. Please try a different one.");
    this.name = "LabelUploadTooLargeError";
  }
}

/** Raised client-side when the content type is not an allowed image type. */
export class LabelUploadInvalidTypeError extends Error {
  constructor() {
    super("This doesn’t appear to be a photo. Please try again.");
    this.name = "LabelUploadInvalidTypeError";
  }
}

/**
 * Raised client-side when the captured/picked file cannot be read at the URI
 * (missing or unreadable). Content-free: it never carries the URI or path.
 */
export class LabelUploadUnreadableError extends Error {
  constructor() {
    super("We couldn’t read that photo. Please try again.");
    this.name = "LabelUploadUnreadableError";
  }
}

/**
 * A readable local image file: the subset of `expo-file-system`'s `File` the
 * upload path needs. Injectable so tests can supply an in-memory fake without a
 * real filesystem — the same seam pattern used across the on-device stores.
 */
export interface LocalImageFile {
  /** Whether the file exists and is readable at its URI. */
  readonly exists: boolean;
  /** File size in bytes, read from disk (0 when missing/unreadable). */
  readonly size: number;
  /** OS-declared MIME type (empty string when missing/unreadable). */
  readonly type: string;
  /**
   * Streams the raw file bytes to `url` as the request body via native
   * networking. Resolves with the response status + body for any completed
   * response (including non-2xx); rejects only on a true network/read failure.
   */
  upload(
    url: string,
    options: {
      httpMethod: "POST";
      uploadType: UploadType;
      headers: Record<string, string>;
      mimeType: string;
    },
  ): Promise<{ status: number; body: string }>;
}

/** Opens a local image URI as a readable `LocalImageFile`. Injectable for tests. */
export type OpenLocalImage = (uri: string) => LocalImageFile;

/** Default opener: `expo-file-system`'s `File`, the repo-standard on-device file API. */
export const openLocalImage: OpenLocalImage = (uri) => new File(uri);

/**
 * Read a captured/picked local image, run the client-side size/type guard, and
 * upload its raw bytes to `url` with the declared image `Content-Type`.
 *
 * The read + upload go through the native `File` API (FTY-381): `File.upload`
 * streams the bytes from disk, so nothing depends on the fragile
 * `fetch(file://).blob()` path that failed silently before the POST. Returns the
 * raw response status + body; the caller maps status → typed error and parses the
 * body. Errors never carry the URI, bytes, or extracted content.
 */
export async function uploadImageBinary(
  url: string,
  token: string,
  imageUri: string,
  openImage: OpenLocalImage = openLocalImage,
): Promise<{ status: number; body: string }> {
  const file = openImage(imageUri);
  if (!file.exists) {
    // No readable file at the URI — surface a content-free error instead of
    // POSTing an empty body (or leaking a native "file not found" path).
    throw new LabelUploadUnreadableError();
  }

  // Normalize content type: camera/library assets may omit the charset part or
  // report an empty type — fall back to jpeg, then guard before any network call.
  const contentType = (file.type || "image/jpeg").split(";")[0].trim().toLowerCase();
  validateImageGuard(file.size, contentType);

  return file.upload(url, {
    httpMethod: "POST",
    uploadType: UploadType.BINARY_CONTENT,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": contentType },
    mimeType: contentType,
  });
}

/**
 * First-line client-side guard: throws if the image exceeds the size limit or is
 * not an allowed image content type. Does not make any network call. The
 * authoritative validation lives in FTY-061's backend (attachments.validate_upload).
 */
export function validateImageGuard(sizeBytes: number, contentType: string): void {
  if (sizeBytes > MAX_UPLOAD_BYTES) {
    throw new LabelUploadTooLargeError();
  }
  const normalized = contentType.split(";")[0].trim().toLowerCase();
  if (!ALLOWED_CONTENT_TYPES.has(normalized)) {
    throw new LabelUploadInvalidTypeError();
  }
}

/**
 * Upload a captured (or picked) nutrition-label photo to the label-upload endpoint.
 *
 * Reads the local image file, runs the client-side size/type guard, then streams
 * the raw image bytes to `/api/users/{userId}/log-events/label?save=...` via the
 * native `File.upload` (FTY-381). The image type travels in the `Content-Type`
 * header and the `save` flag in the query string; the backend persists the raw
 * image as a `log_attachment` only when `save=true`, discarding it after
 * extraction by default (FTY-077).
 *
 * Returns the resulting `LogEventDTO` (the backend extracts in-request, so the
 * event is already at its post-extraction status). Errors carry only HTTP status
 * — never image bytes, URIs, or extracted content.
 */
export async function uploadLabelImage(
  session: ApiSession,
  imageUri: string,
  savePhoto: boolean,
  openImage: OpenLocalImage = openLocalImage,
): Promise<LogEventDTO> {
  const url =
    `${session.baseUrl}/api/users/${encodeURIComponent(session.userId)}/log-events/label` +
    `?save=${savePhoto ? "true" : "false"}`;

  const { status, body } = await uploadImageBinary(
    url,
    session.token,
    imageUri,
    openImage,
  );

  if (status < 200 || status >= 300) {
    // This raw-body path bypasses request(), so it must clear the session on a
    // 401 itself: a dead token here should route back to sign-in just like the
    // JSON funnel. Fire before throwing so the caller's catch/finally still runs.
    if (status === 401) {
      notifyUnauthorized();
    }
    // Map documented statuses to plain, nonjudgmental messages.
    // Never echo image bytes, file paths, extracted content, or the raw status code.
    // A 503 is the FTY-390 retryable transient outcome (nothing persisted): frame it
    // as temporary and invite another attempt, never as a permanent/user-caused error.
    const message =
      status === 401
        ? "Your session has expired. Sign in again to keep logging."
        : status === 413
          ? "That photo is too large to upload."
          : status === 503
            ? "The label service is busy right now. Please try again in a moment."
            : `We couldn’t upload the label (status ${status}).`;
    throw new LabelUploadApiError(status, message);
  }

  return JSON.parse(body) as LogEventDTO;
}
