/**
 * Nutrition-label image upload client (FTY-064).
 *
 * Sends a captured label photo to FTY-061's backend label path using FTY-061's
 * defined upload contract: multipart/form-data with an `image` file field and a
 * `save` flag. A client-side guard rejects oversize or wrong-type payloads before
 * any network call — the authoritative trust boundary is FTY-061's backend.
 *
 * Privacy: errors carry only HTTP status and a fixed action description —
 * never image bytes, file paths, URIs, or extracted content. Nothing is logged.
 */

import type { ApiSession } from "@/state/session";
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
export class LabelUploadApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "LabelUploadApiError";
    this.status = status;
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
 * Upload a captured nutrition-label photo to FTY-061's backend label path.
 *
 * Reads the local image file, runs the client-side size/type guard, then POSTs
 * multipart/form-data to `/api/users/{userId}/log-events/label`. The `save` flag
 * is forwarded to the backend, which persists the raw image as a `log_attachment`
 * only when `true`; the default (`false`) discards it after extraction (FTY-077).
 *
 * Returns the created pending `LogEventDTO`. Errors carry only HTTP status — never
 * image bytes, URIs, or extracted content.
 */
export async function uploadLabelImage(
  session: ApiSession,
  imageUri: string,
  savePhoto: boolean,
  fetchImpl: typeof fetch = fetch,
): Promise<LogEventDTO> {
  // Fetch the local image file to check size and content type before uploading.
  const fileResponse = await fetchImpl(imageUri);
  const blob = await fileResponse.blob();

  // Normalize content type: camera captures may omit the charset part.
  const contentType = (blob.type || "image/jpeg").split(";")[0].trim().toLowerCase();
  validateImageGuard(blob.size, contentType);

  const formData = new FormData();
  // React Native FormData file append uses the { uri, type, name } shape.
  formData.append(
    "image",
    { uri: imageUri, type: contentType, name: "label.jpg" } as unknown as Blob,
  );
  formData.append("save", savePhoto ? "true" : "false");

  const url = `${session.baseUrl}/api/users/${encodeURIComponent(session.userId)}/log-events/label`;
  const response = await fetchImpl(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.token}` },
    body: formData,
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
