/**
 * Nutrition-label image upload client (FTY-064).
 *
 * Sends a captured label photo to the label-upload endpoint defined by
 * `docs/contracts/label-upload.md`: the raw image bytes are the request body, the
 * `Content-Type` header declares the image type, and a `save` query flag carries
 * the FTY-077 retention choice. The backend validates the image as data, runs the
 * FTY-061 extraction pipeline in-request, and returns the resulting log event. A
 * client-side guard rejects oversize or wrong-type payloads before any network
 * call — the authoritative trust boundary is the backend.
 *
 * Privacy: errors carry only HTTP status and a fixed action description —
 * never image bytes, file paths, URIs, or extracted content. Nothing is logged.
 */

import { ApiError } from "@/api/client";
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
 * Upload a captured nutrition-label photo to the label-upload endpoint.
 *
 * Reads the local image file, runs the client-side size/type guard, then POSTs
 * the raw image bytes to `/api/users/{userId}/log-events/label?save=...`. The
 * image type travels in the `Content-Type` header and the `save` flag in the
 * query string; the backend persists the raw image as a `log_attachment` only
 * when `save=true`, discarding it after extraction by default (FTY-077).
 *
 * Returns the resulting `LogEventDTO` (the backend extracts in-request, so the
 * event is already at its post-extraction status). Errors carry only HTTP status
 * — never image bytes, URIs, or extracted content.
 */
export async function uploadLabelImage(
  session: ApiSession,
  imageUri: string,
  savePhoto: boolean,
  fetchImpl: typeof fetch = fetch,
): Promise<LogEventDTO> {
  // Fetch the local image file to read its bytes and check size/type before upload.
  const fileResponse = await fetchImpl(imageUri);
  const blob = await fileResponse.blob();

  // Normalize content type: camera captures may omit the charset part.
  const contentType = (blob.type || "image/jpeg").split(";")[0].trim().toLowerCase();
  validateImageGuard(blob.size, contentType);

  const url =
    `${session.baseUrl}/api/users/${encodeURIComponent(session.userId)}/log-events/label` +
    `?save=${savePhoto ? "true" : "false"}`;
  const response = await fetchImpl(url, {
    method: "POST",
    // Send the raw image bytes as the body; the header declares the image type.
    headers: { Authorization: `Bearer ${session.token}`, "Content-Type": contentType },
    body: blob,
  });

  if (!response.ok) {
    // Map documented statuses to plain, nonjudgmental messages.
    // Never echo image bytes, file paths, or extracted content.
    const message =
      response.status === 401
        ? "Your session has expired. Sign in again to keep logging."
        : response.status === 413
          ? "That photo is too large to upload."
          : `We couldn’t upload the label (status ${response.status}).`;
    throw new LabelUploadApiError(response.status, message);
  }

  return response.json() as Promise<LogEventDTO>;
}
