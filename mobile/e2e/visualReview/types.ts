/**
 * Visual-review preset types (FTY-247).
 *
 * The visual-review mode lets a tester (or the FTY-235..241 screenshot tooling)
 * open a named screen/state directly in the E2E debug build via a deep link —
 * no rebuild, no live backend, no manual state-walking. These types are the
 * shared contract every preset is defined against, whether it is one of the
 * in-scope presets shipped here (`presets.ts`) or a sub-state preset a
 * per-screen seam story (FTY-262..268) contributes through the registration API
 * without editing the shared registry.
 *
 * Nothing here is auth-sensitive on its own — it is data describing how to seed
 * and reach a state. The auth-bypass/mock-API gate lives in `launchMode.ts`
 * (`isE2EMode()`); the visual-review runtime never activates outside it.
 */

/** The request the mock fetch is currently answering, normalised for matching. */
export interface VisualReviewFetchContext {
  /** The full request URL (including any query string). */
  readonly url: string;
  /** The HTTP method, upper-cased. */
  readonly method: string;
  /** The request path with the query string stripped (what suffix matches run against). */
  readonly pathEnd: string;
}

/**
 * A single fetch override a preset installs while it is active. The first
 * response whose `match` returns true answers the request; `body` may be a
 * literal JSON value or a function of the request (e.g. a weight series anchored
 * to the requested `to` window).
 */
export interface VisualReviewResponse {
  /** True when this override should answer the given request. */
  readonly match: (ctx: VisualReviewFetchContext) => boolean;
  /** The JSON body to return, or a function computing it from the request. */
  readonly body: unknown | ((ctx: VisualReviewFetchContext) => unknown);
  /** HTTP status to return (defaults to 200). */
  readonly status?: number;
}

/**
 * A named visual-review state. Activating a preset seeds its fixtures (via
 * `responses`), forces its theme, navigates to `route`, and — once the target
 * screen has loaded and gone quiet — exposes the settled marker
 * `visual-review-settled:<name>` for screenshot automation.
 */
export interface VisualReviewPreset {
  /** Stable dotted name, e.g. `today.populated`. This is the deep-link `preset` value. */
  readonly name: string;
  /**
   * The app route to open for this state (an Expo Router href string), e.g. `/`,
   * `/trends`, `/profile`. Ignored when `signedOut` is set — the auth gate owns
   * the signed-out destination.
   */
  readonly route: string;
  /**
   * The pathname the settled marker waits for (what `usePathname()` reports once
   * the target screen is on top), e.g. `/`, `/trends`, `/signin`.
   */
  readonly settledPath: string;
  /** Default forced theme; the deep-link `theme` param overrides it when present. */
  readonly theme?: 'light' | 'dark';
  /**
   * When true, the preset clears the synthetic session on activation so the auth
   * gate renders the signed-out surface. No fixtures are seeded.
   */
  readonly signedOut?: boolean;
  /** Fetch overrides installed while this preset is active (checked before the default mock). */
  readonly responses?: readonly VisualReviewResponse[];
}
