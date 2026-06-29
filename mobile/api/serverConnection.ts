/**
 * Server-URL validation and the reachability probe for the connect screen
 * (FTY-107).
 *
 * Both inputs that reach this module are **untrusted**: the address the user
 * types, and — more sharply — the payload of a QR scanned from a camera. A
 * malicious QR pointing the app at an attacker-controlled host is the primary
 * threat for this screen, since the connected server is the network target every
 * later request (including the FTY-091 credentials) is sent to. So validation is
 * strict and runs *before* any network call or persistence:
 *
 * - require a well-formed absolute URL,
 * - require an `http(s)` scheme — anything else (`javascript:`, `file:`, app
 *   deep links, …) is rejected, never probed,
 * - normalize to a canonical base (lowercased scheme/host, no trailing slash, no
 *   query or fragment) so it is stored and addressed in one form.
 *
 * The reachability probe is an unauthenticated `GET {base}/healthz` (the
 * documented liveness endpoint, `docs/operations/local-dev-stack.md`) with a
 * timeout. It carries **no personal data** and confirms the host actually speaks
 * Fatty (`{"status":"ok"}`) — a reachable host that is not a Fatty server is
 * treated as unreachable rather than silently accepted.
 */

/** A validated, normalized server base URL. */
export interface ValidServerUrl {
  readonly ok: true;
  /** Canonical base URL: lowercased scheme/host, no trailing slash, no query. */
  readonly url: string;
}

/** A rejected input, with a gentle, user-facing reason. */
export interface InvalidServerUrl {
  readonly ok: false;
  readonly reason: string;
}

export type ServerUrlResult = ValidServerUrl | InvalidServerUrl;

/** Default probe timeout — long enough for a slow home server, short enough to fail fast. */
export const DEFAULT_PROBE_TIMEOUT_MS = 5000;

/**
 * Validate and normalize an untrusted server-address string (typed or scanned).
 * Returns the canonical base URL on success, or a gentle reason on rejection.
 * Performs no network call — malformed input never reaches the probe.
 */
export function validateServerUrl(input: string): ServerUrlResult {
  const trimmed = input.trim();
  if (trimmed === "") {
    return { ok: false, reason: "Enter your server's address." };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return {
      ok: false,
      reason: "That doesn't look like a valid server address.",
    };
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, reason: "Use an http:// or https:// address." };
  }
  if (parsed.hostname === "") {
    return {
      ok: false,
      reason: "That doesn't look like a valid server address.",
    };
  }

  // Canonical base: scheme + host (+ port) + path, no trailing slash, and
  // deliberately no query or fragment — a server base carries none, and dropping
  // them keeps a crafted input from smuggling one through.
  const path = parsed.pathname.replace(/\/+$/, "");
  return { ok: true, url: `${parsed.protocol}//${parsed.host}${path}` };
}

/** Outcome of a reachability probe. */
export type ProbeResult = "reachable" | "unreachable";

/** Body shape of a successful `GET /healthz` (`{"status":"ok"}`). */
interface HealthBody {
  readonly status?: unknown;
}

/**
 * Probe a candidate base URL for reachability with a timeout. Resolves
 * `"reachable"` only when `GET {base}/healthz` answers `200` with the Fatty
 * liveness body (`{"status":"ok"}`); a timeout, a network failure, a non-2xx
 * status, or a non-Fatty body all resolve `"unreachable"`. Never throws.
 *
 * @param baseUrl A canonical base URL from {@link validateServerUrl}.
 */
export async function probeServer(
  baseUrl: string,
  {
    fetchImpl = fetch,
    timeoutMs = DEFAULT_PROBE_TIMEOUT_MS,
  }: { fetchImpl?: typeof fetch; timeoutMs?: number } = {},
): Promise<ProbeResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${baseUrl}/healthz`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) {
      return "unreachable";
    }
    const body = (await response.json()) as HealthBody;
    return body?.status === "ok" ? "reachable" : "unreachable";
  } catch {
    // Timeout (abort), network-layer failure, or unparseable body → unreachable.
    return "unreachable";
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The user-facing host label for the "Can't reach {host}" error. Falls back to
 * the full URL if it cannot be parsed (it always can for a validated URL).
 */
export function displayHost(baseUrl: string): string {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl;
  }
}
