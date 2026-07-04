/**
 * E2E launch mode — deterministic dev-build harness (FTY-160).
 *
 * When active, this module:
 *   1. Seeds a synthetic authenticated session so the app boots past sign-in
 *      with no live auth dependency.
 *   2. Installs a global fetch mock so all API calls return hermetic fixtures
 *      with no live backend or network timing.
 *   3. Marks onboarding complete for the E2E user so the onboarding wizard
 *      never appears (the fixture profile already satisfies the check, but
 *      the module-level flag skips the async check altogether).
 *
 * SECURITY: This module is an auth bypass and a mock-API switch. It is
 * hard-gated by `__DEV__` (a React Native compile-time constant that Metro
 * sets to `false` in release/production builds, dead-code-eliminating this
 * entire branch). The `EXPO_PUBLIC_FATTY_E2E` env var provides a second gate
 * so only an explicitly built E2E debug binary can enter this mode.
 *
 * The mode is off by default and cannot be entered in a release build:
 *   - `__DEV__` is always `false` in release builds → isE2EMode() always false.
 *   - The env var is set only by `verify-e2e.sh` at build time, never by default.
 *   - `setupE2EMode()` and `installE2EMockFetch()` are no-ops when isE2EMode()
 *     returns false.
 */

import { AccessibilityInfo } from 'react-native';
import type { PermissionResponse } from 'expo';
import type { useCameraPermissions } from 'expo-camera';
import { markOnboardingComplete } from '@/state/onboardingComplete';
import type { SessionStore } from '@/state/sessionStore';
import type { ServerConnectionStore } from '@/state/serverConnectionStore';
import {
  E2E_SESSION,
  E2E_SERVER_URL,
  E2E_CAMERA_PERMISSION_GRANTED,
  E2E_FIXTURE_MAP,
  E2E_DAILY_SUMMARY,
  E2E_GOAL_TARGET_RESPONSE,
  E2E_ACTIVE_GOAL,
  E2E_CLARIFY_EVENT,
  E2E_CLARIFICATION,
  E2E_CLARIFY_PROCESSING_EVENT,
  E2E_CLARIFY_RESOLVED_EVENT,
  E2E_RESOLVED_EVENT,
  E2E_RESOLVED_SUMMARY,
  E2E_FAILED_RAW_TEXT,
  E2E_FAILED_EVENT,
  E2E_FAILED_RETRY_EVENT,
  E2E_RESOLVE_RAW_TEXT,
  E2E_RESOLVE_PENDING_EVENT,
  E2E_RESOLVE_EVENT,
  E2E_RESOLVE_ENTRY,
  E2E_RESOLVE_SUMMARY,
  E2E_CORRECTION_RAW_TEXT,
  E2E_CORRECTION_EVENT,
  E2E_CORRECTION_ENTRY,
  E2E_CORRECTION_SUMMARY,
  E2E_CORRECTION_ITEM_ID,
  E2E_CORRECTION_EDITED_ITEM,
  E2E_TARGET_RAW_TEXT,
  E2E_TARGET_EVENT,
  E2E_TARGET_ENTRY,
  E2E_TARGET_SUMMARY,
  E2E_OCCLUSION_RAW_TEXT,
  E2E_OCCLUSION_PENDING_EVENT,
  E2E_OCCLUSION_EVENT,
  E2E_OCCLUSION_ENTRY,
  E2E_OCCLUSION_SUMMARY,
  e2eWeightEntries,
  e2eDailySummaryRange,
  E2E_SAVED_FOOD,
  E2E_SAVED_FOOD_EVENT,
  E2E_SAVED_FOOD_ITEM_ID,
  E2E_SAVED_FOOD_EDITED_ITEM,
  E2E_SOURCE_CANDIDATE,
  E2E_RERESOLVED_ITEM,
} from './fixtures';
import {
  E2E_BARCODE_RAW_TEXT,
  E2E_BARCODE_PENDING_EVENT,
  E2E_BARCODE_EVENT,
  E2E_BARCODE_ENTRY,
  E2E_BARCODE_SUMMARY,
} from './barcodeFixtures';

/**
 * True only in a DEV build that was compiled with EXPO_PUBLIC_FATTY_E2E=true.
 *
 * In release builds `__DEV__` is `false` (compile-time constant) so this
 * function always returns `false` and Metro dead-code-eliminates the branch.
 */
export function isE2EMode(): boolean {
  if (!__DEV__) return false;
  return process.env.EXPO_PUBLIC_FATTY_E2E === 'true';
}

/**
 * True when the E2E harness should force Reduce Motion ON (FTY-181).
 *
 * The signature beats degrade to a simple fade / value-set (no spring) under
 * Reduce Motion. Maestro cannot toggle the OS `isReduceMotionEnabled` flag, so a
 * reduce-motion E2E build sets this second env var and the harness overrides the
 * accessibility read — the hermetic equivalent of the OS toggle — letting the
 * `reduce-motion.yaml` flow verify the beats still complete on their no-motion
 * branch. Gated behind `isE2EMode()` so it is dead code in release builds.
 */
export function isE2EReduceMotionMode(): boolean {
  if (!isE2EMode()) return false;
  return process.env.EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION === 'true';
}

/**
 * In-memory session store pre-seeded with the E2E synthetic session.
 * Injected into SessionProvider in place of the real SecureStore when E2E mode
 * is active. No data is written to the device keychain.
 */
export const e2eSessionStore: SessionStore = {
  async save() {},
  async load() {
    return E2E_SESSION;
  },
  async clear() {},
};

/**
 * In-memory connection store pre-seeded with the E2E server URL.
 * Injected into ConnectionProvider in place of the real file store when E2E
 * mode is active. No data is written to the device filesystem.
 */
export const e2eConnectionStore: ServerConnectionStore = {
  async load() {
    return E2E_SERVER_URL;
  },
  async save() {},
  async clear() {},
};

/**
 * E2E camera-permission hook (FTY-194). Drop-in for expo-camera's
 * `useCameraPermissions`, returning an already-granted permission so the
 * barcode scanner renders its granted chrome — reticle, torch, and the
 * "Type it instead" fallback — without a device camera. `CameraCapture`
 * defaults to this hook when `isE2EMode()` is true, so the
 * `barcode-manual-entry.yaml` flow can drive the real scanner path on the
 * simulator. `request`/`get` resolve to the same granted response; nothing is
 * ever asked of the OS. Dead code in release builds (never reached off E2E).
 */
export const e2eCameraPermissionsHook: typeof useCameraPermissions = () => {
  const grant = async (): Promise<PermissionResponse> =>
    E2E_CAMERA_PERMISSION_GRANTED;
  return [E2E_CAMERA_PERMISSION_GRANTED, grant, grant];
};

/**
 * Build the E2E mock fetch function. Returns hermetic fixture JSON for every
 * API call the app makes — no network I/O. The mock is stateful: it tracks the
 * clarify-flow phase so the smoke flow (FTY-160) and the clarify flow (FTY-162)
 * can share one binary without conflicting fixture state.
 *
 * Phase transitions:
 *   phase 0 — empty day (smoke test; no POST made)
 *   phase 1 — needs_clarification entry visible (after first POST /log-events)
 *   phase 2 — entry resolved and counting, reached two ways:
 *             • clarify flow (FTY-175): POST /clarification/answers resolves the
 *               same event in place (→ processing), raw phrase untouched; or
 *             • smoke flow (FTY-178): a second POST /log-events re-submission.
 *
 * The two phase-2 routes serve different day-lists, because they model
 * different server behaviour: the answer route resolves the SAME event in
 * place, so GET returns E2E_CLARIFY_RESOLVED_EVENT — identical id, raw_text,
 * and created_at, now `completed` — which is what lets clarify.yaml prove the
 * no-duplicate, same-entry resolution end-to-end. The re-submission route
 * genuinely created a second event, so GET returns the distinct-id
 * E2E_RESOLVED_EVENT.
 *
 * The smoke flow (FTY-178) asserts the phase-0 empty-day hero first, then
 * POSTs twice to walk the phase machine to the resolved, counting summary. The
 * clarify flow (FTY-162) submits once, opens the sheet, and taps a chip — the
 * answer round-trip advances the same event to the resolved phase.
 *
 * The FTY-176 failed-parse flow runs off a separate `failedStage` keyed on the
 * gibberish `raw_text` (never "coffee"), so it drives independent state in the
 * same binary: stage 0 → first gibberish POST returns a `failed` event; stage 1
 * → a Retry POST returns a fresh `pending` attempt. GET reflects the stage so a
 * poll never drops the reconciled server row.
 *
 * The FTY-181 signature-beat flows each run off their own stage keyed on a
 * distinct `raw_text`, independent of every machine above:
 *   - `resolveStage` (beat 1): a log first appears pending, then resolves to a
 *     completed entry whose item-forward feed carries multiple items summarized
 *     into one event row so the no-layout-shift resolve path is reachable.
 *   - `correctionStage` (beat 2): the log resolves to a tappable resolved row;
 *     a PATCH to its item returns the recomputed value the correction beat rides.
 *   - `targetStage` (beat 3): a single large entry resolves and the day summary
 *     crosses the calorie target, so the hero flips to its over-budget state.
 */
export function createE2EMockFetch(): typeof fetch {
  let phase: 0 | 1 | 2 = 0;
  let failedStage: 0 | 1 | 2 = 0;
  // FTY-181 entry-resolve flow: 0 before the log, 1 once the pending resolve
  // entry is created. Keyed on its own raw_text so it stays independent of the
  // clarify "coffee" phase machine and the gibberish failed flow.
  let resolveStage: 0 | 1 = 0;
  // FTY-181 correction-saved (beat 2) flow: 0 before the log, 1 once the
  // correction entry (a tappable resolved row) is created. A PATCH to its item
  // then returns the recomputed value the beat rides. Keyed on its own raw_text.
  let correctionStage: 0 | 1 = 0;
  // FTY-181 target-reached (beat 3) flow: 0 before the log, 1 once the large
  // entry that crosses the calorie target is created, flipping the day summary
  // over target. Keyed on its own raw_text.
  let targetStage: 0 | 1 = 0;
  // FTY-185 tab-bar occlusion flow: 0 before the log, 1 once the multi-item
  // "big mixed plate" entry is created, so GET serves a long timeline that
  // scrolls beneath the floating tab bar. Keyed on its own raw_text.
  let occlusionStage: 0 | 1 = 0;
  // FTY-225 barcode manual-entry flow: 0 before the log, 1 once the seeded
  // "1 serving of greek yogurt" entry is created. POST returns it pending
  // (skeleton visible); a refresh GET then serves the completed event whose
  // by-date feed carries the resolved packaged-food item, and the day summary
  // counts it. Keyed on its own raw_text.
  let barcodeStage: 0 | 1 = 0;
  // How phase 2 was reached — decides which day-list GET serves (see above).
  let resolvedVia: 'answer' | 'resubmit' | null = null;
  // FTY-183 correction flow: set once the saved food is submitted so GET
  // /log-events keeps returning its completed event (a poll never drops the row
  // the CorrectionSheet is opened from). Keyed on the saved food's raw_text, it
  // stays independent of the clarify/failed phase machines above.
  let savedFoodCreated = false;
  // FTY-183 weight flow: the last weight (kg) saved via POST /weight-entries.
  // Once set, GET upserts today's point to it so the refetched Trends headline
  // reflects the save — the load-bearing proof the save round-tripped.
  let savedWeightKg: number | null = null;

  const rawTextOf = (init?: RequestInit): string | undefined => {
    if (typeof init?.body !== 'string') return undefined;
    try {
      return (JSON.parse(init.body) as { raw_text?: string }).raw_text;
    } catch {
      return undefined;
    }
  };

  const json = (body: unknown, status = 200): Response =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });

  // Read a query-string parameter off a full request URL (the Trends range/weight
  // reads carry the from/to window the fixtures are anchored to).
  const queryParam = (u: string, key: string): string | undefined => {
    const q = u.split('?')[1];
    if (!q) return undefined;
    for (const pair of q.split('&')) {
      const [k, v] = pair.split('=');
      if (k === key) return decodeURIComponent(v ?? '');
    }
    return undefined;
  };

  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;

    const method = (
      init?.method ?? (input instanceof Request ? input.method : 'GET')
    ).toUpperCase();

    const pathEnd = url.split('?')[0];

    // /log-events/by-date — the item-forward day feed (FTY-198): each event with
    // its derived items. This is the read the entry-resolve beat (FTY-181) needs,
    // since the value row only renders when the feed carries the entry's items.
    // The clarify/smoke/failed flows serve `items: []` so their rows keep
    // rendering the raw phrase (no value row); only the resolve flow carries a
    // real items, so resolve.yaml can assert both resolved rows on-device.
    // Matched before `/log-events` because the URL suffix is more specific.
    if (pathEnd.endsWith('/log-events/by-date')) {
      if (failedStage === 1) return json([{ event: E2E_FAILED_EVENT, items: [] }]);
      if (failedStage === 2)
        return json([{ event: E2E_FAILED_RETRY_EVENT, items: [] }]);
      if (resolveStage === 1) return json([E2E_RESOLVE_ENTRY]);
      if (correctionStage === 1) return json([E2E_CORRECTION_ENTRY]);
      if (targetStage === 1) return json([E2E_TARGET_ENTRY]);
      if (occlusionStage === 1) return json([E2E_OCCLUSION_ENTRY]);
      if (barcodeStage === 1) return json([E2E_BARCODE_ENTRY]);
      if (phase === 0) return json([]);
      if (phase === 1) return json([{ event: E2E_CLARIFY_EVENT, items: [] }]);
      return json([
        {
          event:
            resolvedVia === 'answer'
              ? E2E_CLARIFY_RESOLVED_EVENT
              : E2E_RESOLVED_EVENT,
          items: [],
        },
      ]);
    }

    // /log-events — POST advances state and returns the next event;
    // GET returns the state-appropriate event list.
    if (pathEnd.endsWith('/log-events')) {
      if (method === 'POST') {
        // FTY-176 failed-parse flow: gibberish text fails first, then a Retry
        // produces a fresh pending attempt. Keyed on raw_text so it never
        // collides with the clarify flow's "coffee" phase machine.
        if (rawTextOf(init) === E2E_FAILED_RAW_TEXT) {
          if (failedStage === 0) {
            failedStage = 1;
            return json(E2E_FAILED_EVENT, 201);
          }
          failedStage = 2;
          return json(E2E_FAILED_RETRY_EVENT, 201);
        }
        // FTY-183 correction flow: submitting the saved food resolves straight to
        // a completed event (keyed on its name, independent of the coffee phase
        // machine). The resolved synthetic item TodayScreen inserts is what the
        // CorrectionSheet then opens against.
        if (rawTextOf(init) === E2E_SAVED_FOOD.name) {
          savedFoodCreated = true;
          return json(E2E_SAVED_FOOD_EVENT, 201);
        }
        // FTY-181 entry-resolve flow: POST returns the stored pending event so
        // the skeleton is visible on-device; a subsequent GET returns the same
        // event completed with multiple by-date items summarized into one row.
        // Keyed on its own raw_text so it never disturbs the clarify phase
        // machine.
        if (rawTextOf(init) === E2E_RESOLVE_RAW_TEXT) {
          resolveStage = 1;
          return json(E2E_RESOLVE_PENDING_EVENT, 201);
        }
        // FTY-181 correction-saved (beat 2): the log resolves to a completed
        // entry whose resolved row is tappable; the PATCH below then commits the
        // correction the beat rides. Keyed on its own raw_text.
        if (rawTextOf(init) === E2E_CORRECTION_RAW_TEXT) {
          correctionStage = 1;
          return json(E2E_CORRECTION_EVENT, 201);
        }
        // FTY-181 target-reached (beat 3): a single large entry resolves and the
        // day summary crosses the calorie target, arming the crossing beat.
        if (rawTextOf(init) === E2E_TARGET_RAW_TEXT) {
          targetStage = 1;
          return json(E2E_TARGET_EVENT, 201);
        }
        // FTY-185 tab-bar occlusion: the seed appears pending first (skeleton),
        // then a pull-to-refresh GET resolves it to a long multi-item timeline
        // the flow scrolls under the floating tab bar. Keyed on its own raw_text.
        if (rawTextOf(init) === E2E_OCCLUSION_RAW_TEXT) {
          occlusionStage = 1;
          return json(E2E_OCCLUSION_PENDING_EVENT, 201);
        }
        // FTY-225 barcode manual-entry: the seeded "1 serving of …" phrase
        // appears pending first (skeleton), then a pull-to-refresh GET resolves
        // it to the counted packaged-food item. Keyed on its own raw_text.
        if (rawTextOf(init) === E2E_BARCODE_RAW_TEXT) {
          barcodeStage = 1;
          return json(E2E_BARCODE_PENDING_EVENT, 201);
        }
        if (phase === 0) {
          phase = 1;
          return json(E2E_CLARIFY_EVENT, 201);
        }
        phase = 2;
        resolvedVia = 'resubmit';
        return json(E2E_RESOLVED_EVENT, 201);
      }
      // The failed-parse flow's GET reflects its own stage so a poll never drops
      // the reconciled failed / retry-pending row.
      if (failedStage === 1) return json([E2E_FAILED_EVENT]);
      if (failedStage === 2) return json([E2E_FAILED_RETRY_EVENT]);
      // FTY-183 correction flow: keep serving the completed saved-food event so
      // its resolved timeline row survives a poll while the sheet is open.
      if (savedFoodCreated) return json([E2E_SAVED_FOOD_EVENT]);
      // The resolve flow's GET lists the completed entry so a Refresh/poll keeps
      // the reconciled row (its items ride the by-date feed above).
      if (resolveStage === 1) return json([E2E_RESOLVE_EVENT]);
      // The correction / target flows likewise list their completed entry so a
      // poll never drops the reconciled row (their items ride the feed above).
      if (correctionStage === 1) return json([E2E_CORRECTION_EVENT]);
      if (targetStage === 1) return json([E2E_TARGET_EVENT]);
      if (occlusionStage === 1) return json([E2E_OCCLUSION_EVENT]);
      // The barcode flow's GET likewise lists its completed entry so a
      // refresh/poll keeps the reconciled row (items ride the feed above).
      if (barcodeStage === 1) return json([E2E_BARCODE_EVENT]);
      if (phase === 0) return json([]);
      if (phase === 1) return json([E2E_CLARIFY_EVENT]);
      // Resolved via the answer round-trip → the SAME event, now completed
      // (same id, raw phrase, created_at — the no-duplicate proof clarify.yaml
      // asserts). Resolved via re-submission → the genuinely-new second event.
      return json([
        resolvedVia === 'answer' ? E2E_CLARIFY_RESOLVED_EVENT : E2E_RESOLVED_EVENT,
      ]);
    }

    // /derived-items/{type}/{id} — the FTY-092 correction commit (a single-field
    // PATCH). The correction-saved beat (FTY-181, beat 2) fires on a successful
    // commit, so the mock echoes the recomputed item for the correction flow's
    // amount step; correction.yaml asserts its 175-kcal value on-device. Matched
    // on the item id so it never intercepts an unrelated PATCH.
    //
    // FTY-245: the saved-food correction sheet's Portion (amount) stepper PATCHes
    // the same endpoint against the saved-food synthetic item's derived-item id
    // (E2E_SAVED_FOOD_ITEM_ID). Without this branch that PATCH fell through to the
    // 404 default below and the sheet surfaced "We couldn't find that item."
    // Matched on the item id exactly, like the correction branch above, so it
    // never intercepts an unrelated PATCH (e.g. the correction item's).
    if (method === 'PATCH' && pathEnd.includes('/derived-items/')) {
      if (pathEnd.endsWith(`/${E2E_CORRECTION_ITEM_ID}`)) {
        return json(E2E_CORRECTION_EDITED_ITEM);
      }
      if (pathEnd.endsWith(`/${E2E_SAVED_FOOD_ITEM_ID}`)) {
        return json(E2E_SAVED_FOOD_EDITED_ITEM);
      }
    }

    // /clarification/answers — the first-class clarify resolve (FTY-170). A
    // POST applies the answer to the SAME event in place, advances to the
    // resolved phase, and returns that event now `processing` (its id and raw
    // phrase unchanged — no duplicate, no phrase mutation). GET /log-events then
    // reflects the resolved, counting entry.
    if (pathEnd.endsWith('/clarification/answers')) {
      if (method === 'POST') {
        phase = 2;
        resolvedVia = 'answer';
        return json(E2E_CLARIFY_PROCESSING_EVENT, 201);
      }
    }

    // /clarification — the clarify sheet's lazy question-read.
    if (pathEnd.endsWith('/clarification')) {
      return json(E2E_CLARIFICATION);
    }

    // /daily-summary/range — backs the Trends adherence card (FTY-187). Returns
    // one summary per calendar day in the requested window, anchored to the same
    // from/to the client derived from the device clock, so the card renders real
    // on-target days rather than an empty/error state.
    if (pathEnd.endsWith('/daily-summary/range')) {
      const from = queryParam(url, 'from');
      const to = queryParam(url, 'to');
      return json(from && to ? e2eDailySummaryRange(from, to) : []);
    }

    // /daily-summary — returns non-zero intake once the entry is resolved
    // (the resolve flow's two-item 245-kcal entry, or the clarify/smoke 120-kcal
    // coffee).
    // The target flow returns the over-budget 2,100-kcal summary so the hero
    // crosses its calorie target and beat 3 arms; the correction flow keeps the
    // pre-edit 140 kcal (its beat rides the PATCH, not the day total).
    if (pathEnd.endsWith('/daily-summary')) {
      if (resolveStage === 1) return json(E2E_RESOLVE_SUMMARY);
      if (targetStage === 1) return json(E2E_TARGET_SUMMARY);
      if (correctionStage === 1) return json(E2E_CORRECTION_SUMMARY);
      if (occlusionStage === 1) return json(E2E_OCCLUSION_SUMMARY);
      if (barcodeStage === 1) return json(E2E_BARCODE_SUMMARY);
      return json(phase === 2 ? E2E_RESOLVED_SUMMARY : E2E_DAILY_SUMMARY);
    }

    // /weight-entries — backs the Trends weight card (FTY-187/183). GET returns
    // the synthetic series anchored to the window's end (`to` = the device's
    // today). A POST (a weight save) echoes the submitted weight/date back AND
    // records it, so a subsequent GET upserts today's point to the saved weight —
    // the refetched Trends headline then reflects the save, which is the
    // load-bearing proof trends.yaml asserts that the log/save round-trips.
    if (pathEnd.endsWith('/weight-entries')) {
      if (method === 'POST') {
        const body =
          typeof init?.body === 'string'
            ? (JSON.parse(init.body) as {
                weight?: number;
                effective_date?: string;
              })
            : {};
        const date = body.effective_date ?? '2026-01-01';
        const weight = body.weight ?? 75;
        savedWeightKg = weight;
        return json(
          {
            id: 'e2e-weight-created',
            user_id: E2E_SESSION.userId,
            weight_kg: weight,
            effective_date: date,
            created_at: `${date}T08:00:00Z`,
            updated_at: `${date}T08:00:00Z`,
          },
          201,
        );
      }
      const to = queryParam(url, 'to') ?? '2026-01-01';
      const series = e2eWeightEntries(to);
      // One weight per calendar day: a save for today upserts the window's last
      // point (the device's today) to the saved value, so the refetched series —
      // and the EWMA headline recomputed from it — carries the just-saved weight.
      if (savedWeightKg !== null && series.length > 0) {
        const last = series[series.length - 1]!;
        series[series.length - 1] = { ...last, weight_kg: savedWeightKg };
      }
      return json(series);
    }

    // /derived-items/food/{id}/source-candidates — the Change-match panel's
    // alternative-source list (FTY-093). Returns one candidate the correction
    // flow re-resolves to. Matched before the generic derived-items paths.
    if (pathEnd.endsWith('/source-candidates')) {
      return json({ candidates: [E2E_SOURCE_CANDIDATE] });
    }

    // /derived-items/food/{id}/re-resolve — commit the Change-match pick
    // (FTY-093/183). Returns the same item with honest new provenance and
    // server-recomputed values, which the sheet + timeline re-render in place.
    if (pathEnd.endsWith('/re-resolve')) {
      return json(E2E_RERESOLVED_ITEM);
    }

    // /saved-foods — the FTY-053 typeahead search backing the correction flow's
    // saved-food pick. Returns the seeded saved food when the query prefix/
    // substring matches its name (mirrors the server's contains semantics), so
    // the suggestion chip appears as the user types; empty otherwise, so it never
    // surfaces for the clarify/failed flows' inputs.
    if (pathEnd.endsWith('/saved-foods') && method === 'GET') {
      const q = (queryParam(url, 'q') ?? '').trim().toLowerCase();
      const match = q.length > 0 && E2E_SAVED_FOOD.name.toLowerCase().includes(q);
      return json({ items: match ? [E2E_SAVED_FOOD] : [], limit: 10 });
    }

    // /goal — POST creates/replaces the active goal and returns the goal +
    // target reveal (FTY-106). Backs the FTY-182 profile flow: saving a goal
    // edit under the native header resolves to the mini target-reveal, then
    // SettingsScreen refetches GET /target (served below) for the full macros.
    // GET answers the FTY-189/FTY-190 read model (direction + pace, both
    // recovered server-side from the persisted trajectory) so a cold-launched
    // Settings screen summarises the returning user's real goal as
    // `Goal: Lose · Steady` (matching the seeded loss/steady trajectory) instead
    // of the dead "Active" / neutral "Details unavailable" states — the FTY-190
    // outcome the settings-fty190.yaml flow proves on the running app.
    if (pathEnd.endsWith('/goal')) {
      if (method === 'POST') return json(E2E_GOAL_TARGET_RESPONSE, 201);
      if (method === 'GET') return json(E2E_ACTIVE_GOAL);
    }

    // Static fixtures (profile, target).
    for (const [suffix, fixture] of Object.entries(E2E_FIXTURE_MAP)) {
      if (pathEnd.endsWith(suffix)) {
        return json(fixture);
      }
    }

    return json({ detail: 'E2E fixture not found for this URL' }, 404);
  };
}

/**
 * Replace the global `fetch` with the E2E mock. No-op when isE2EMode() is
 * false (release builds, normal dev builds without the flag).
 *
 * Must be called before any API call is made — in practice, called at the
 * module-load-time side effect in app/_layout.tsx.
 */
export function installE2EMockFetch(): void {
  if (!isE2EMode()) return;
  // globalThis.fetch is available in RN JS environments; cast because the
  // TypeScript lib declares it read-only but RN lets tests/harnesses override it.
  (globalThis as Record<string, unknown>)['fetch'] = createE2EMockFetch();
}

/**
 * Force Reduce Motion ON for the reduce-motion E2E build (FTY-181). No-op unless
 * isE2EReduceMotionMode() — so it never affects the default motion-on suite or a
 * release build. Overrides `AccessibilityInfo.isReduceMotionEnabled` to resolve
 * `true`, the read the signature beats (theme/motion.ts) branch on; this is the
 * hermetic equivalent of the OS accessibility toggle Maestro cannot flip.
 */
export function applyE2EReduceMotion(): void {
  if (!isE2EReduceMotionMode()) return;
  // The RN typings declare the static as read-only; the runtime object is a
  // plain singleton the harness may override, mirroring the fetch override above.
  (AccessibilityInfo as unknown as Record<string, unknown>)[
    'isReduceMotionEnabled'
  ] = () => Promise.resolve(true);
}

/**
 * One-shot E2E mode setup called at app startup (from app/_layout.tsx).
 * No-op when isE2EMode() is false.
 *
 *  - Installs the mock fetch so all API calls use fixture responses.
 *  - Marks onboarding complete for the E2E user so AuthGate skips the async
 *    profile/goals check and routes straight to Today.
 *  - Forces Reduce Motion on when the reduce-motion E2E build is active, so the
 *    signature beats take their no-motion branch for the reduce-motion flow.
 */
export function setupE2EMode(): void {
  if (!isE2EMode()) return;
  installE2EMockFetch();
  markOnboardingComplete(E2E_SESSION.userId);
  applyE2EReduceMotion();
}
