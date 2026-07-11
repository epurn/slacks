/**
 * E2E launch mode gate tests (FTY-160).
 *
 * These tests assert the fail-closed security properties:
 *   1. The mode is off by default (no env var set).
 *   2. The mode cannot be entered when __DEV__ is false (release build path).
 *   3. The mode IS on when both gates pass (dev build + env var).
 *   4. The mock fetch is not installed when the mode is off.
 *   5. The E2E stores return the correct synthetic data.
 */

// jest.mock hoisted above imports (required by eslint-config-expo import/first rule).
jest.mock('@/state/onboardingComplete', () => ({
  markOnboardingComplete: jest.fn(),
  isOnboardingCompleteForUser: jest.fn(() => false),
  clearOnboardingComplete: jest.fn(),
}));

// eslint-disable-next-line import/first
import {
  isE2EMode,
  isE2EReduceMotionMode,
  applyE2EReduceMotion,
  e2eSessionStore,
  e2eConnectionStore,
  e2eCameraPermissionsHook,
  installE2EMockFetch,
  createE2EMockFetch,
  setupE2EMode,
} from './launchMode';
// eslint-disable-next-line import/first
import {
  E2E_SESSION,
  E2E_SERVER_URL,
  E2E_CLARIFY_EVENT_ID,
  E2E_CLARIFY_QUESTION,
  E2E_CLARIFY_QUESTION_ID,
  E2E_CLARIFY_OPTIONS,
  E2E_CLARIFY_EVENT,
  E2E_CLARIFY_RESOLVED_EVENT,
  E2E_RESOLVED_EVENT,
  E2E_RESOLVED_EVENT_TIME_LABEL,
  E2E_FAILED_RAW_TEXT,
  E2E_FAILED_EVENT,
  E2E_FAILED_RETRY_EVENT,
  E2E_GOAL_TARGET_RESPONSE,
  E2E_ACTIVE_GOAL,
  E2E_SAVED_FOOD,
  E2E_SAVED_FOOD_EVENT_ID,
  E2E_SAVED_FOOD_ITEM_ID,
  E2E_SAVED_FOOD_EDITED_ITEM,
  E2E_SOURCE_CANDIDATE,
  E2E_RESOLVE_RAW_TEXT,
  E2E_RESOLVE_EVENT_ID,
  E2E_RESOLVE_ITEM,
  E2E_CORRECTION_RAW_TEXT,
  E2E_CORRECTION_EVENT_ID,
  E2E_CORRECTION_ITEM_ID,
  E2E_CORRECTION_ITEM,
  E2E_CORRECTION_EDITED_ITEM,
  E2E_TARGET_RAW_TEXT,
  E2E_TARGET_EVENT_ID,
  E2E_TARGET_ITEM,
} from './fixtures';
// eslint-disable-next-line import/first
import { formatWallClockTime } from '@/state/today';
// eslint-disable-next-line import/first
import { markOnboardingComplete } from '@/state/onboardingComplete';
// The real API clients — driven through the mock so the fixture suffixes are
// validated against the URLs the app actually requests, not fabricated ones.
// eslint-disable-next-line import/first
import { toApiSession } from '@/state/session';
// eslint-disable-next-line import/first
import { getProfile } from '@/api/profile';
// eslint-disable-next-line import/first
import { createGoal, getActiveGoal, getTarget } from '@/api/goals';
// eslint-disable-next-line import/first
import {
  listTodayLogEvents,
  listTodayLogEventEntries,
  createLogEvent,
  deleteLogEvent,
  getLogEventClarification,
  answerClarification,
} from '@/api/logEvents';
// eslint-disable-next-line import/first
import { getDailySummary, getDailySummaryRange } from '@/api/dailySummary';
// eslint-disable-next-line import/first
import { editDerivedItem } from '@/api/derivedItems';
// eslint-disable-next-line import/first
import { listWeightEntries, createWeightEntry } from '@/api/weightEntries';
// eslint-disable-next-line import/first
import { searchSavedFoods } from '@/api/savedFoods';
// eslint-disable-next-line import/first
import { listSourceCandidates, reResolveItem } from '@/api/corrections';
// eslint-disable-next-line import/first
import { AccessibilityInfo } from 'react-native';
// Registers the in-scope preset manifest so the store can reflect a real preset.
// eslint-disable-next-line import/first
import './visualReview/presets';
// eslint-disable-next-line import/first
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from './visualReview/session';

// jest-expo sets __DEV__ = true globally. Use globalThis so TypeScript is happy
// without needing @types/node (which the project excludes from "types").
const gThis = globalThis as Record<string, unknown>;

// Capture originals so each test can restore them in afterEach.
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;
const ORIGINAL_E2E_REDUCE_MOTION_ENV =
  process.env.EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION;
const ORIGINAL_FETCH = gThis['fetch'] as typeof fetch;
const ORIGINAL_IS_REDUCE_MOTION_ENABLED =
  AccessibilityInfo.isReduceMotionEnabled;

afterEach(() => {
  gThis['__DEV__'] = ORIGINAL_DEV;
  gThis['fetch'] = ORIGINAL_FETCH;
  // Restore the original env value (undefined means the var was absent).
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E'] = ORIGINAL_E2E_ENV;
  }
  if (ORIGINAL_E2E_REDUCE_MOTION_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION'] =
      ORIGINAL_E2E_REDUCE_MOTION_ENV;
  }
  // Restore the accessibility read a reduce-motion test may have overridden.
  (AccessibilityInfo as unknown as Record<string, unknown>)[
    'isReduceMotionEnabled'
  ] = ORIGINAL_IS_REDUCE_MOTION_ENABLED;
  jest.clearAllMocks();
});

// Helper to set the E2E env var in tests. Centralised so the bracket-notation
// access (required for delete/assign) is in one place rather than every test.
function setE2EEnv(value: string | undefined): void {
  if (value === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E'] = value;
  }
}

// Set the reduce-motion E2E env var (FTY-181), centralised for the same reason.
function setE2EReduceMotionEnv(value: string | undefined): void {
  if (value === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E_REDUCE_MOTION'] = value;
  }
}

// ─── isE2EMode gate ──────────────────────────────────────────────────────────

describe('isE2EMode', () => {
  it('is off by default (no env var)', () => {
    setE2EEnv(undefined);
    expect(isE2EMode()).toBe(false);
  });

  it('is off when env var is set but __DEV__ is false (release build path)', () => {
    setE2EEnv('true');
    gThis['__DEV__'] = false;
    // Critical fail-closed assertion: a release build cannot enter E2E mode
    // even if the env var were somehow present in the bundle.
    expect(isE2EMode()).toBe(false);
  });

  it('is off when __DEV__ is true but env var is missing', () => {
    gThis['__DEV__'] = true;
    setE2EEnv(undefined);
    expect(isE2EMode()).toBe(false);
  });

  it('is on when __DEV__ is true AND env var is "true"', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    expect(isE2EMode()).toBe(true);
  });

  it('is off when env var is present but not exactly "true"', () => {
    gThis['__DEV__'] = true;

    setE2EEnv('1');
    expect(isE2EMode()).toBe(false);

    setE2EEnv('TRUE');
    expect(isE2EMode()).toBe(false);

    setE2EEnv('yes');
    expect(isE2EMode()).toBe(false);
  });
});

// ─── isE2EReduceMotionMode gate (FTY-181) ────────────────────────────────────

describe('isE2EReduceMotionMode', () => {
  it('is off by default, even in E2E mode (motion on)', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    setE2EReduceMotionEnv(undefined);
    expect(isE2EReduceMotionMode()).toBe(false);
  });

  it('requires E2E mode: the reduce-motion var alone does nothing', () => {
    gThis['__DEV__'] = true;
    setE2EEnv(undefined);
    setE2EReduceMotionEnv('true');
    // Fail-closed: without the E2E gate the reduce-motion override never applies.
    expect(isE2EReduceMotionMode()).toBe(false);
  });

  it('is on when E2E mode is on AND the reduce-motion var is exactly "true"', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    setE2EReduceMotionEnv('true');
    expect(isE2EReduceMotionMode()).toBe(true);
  });

  it('is off for the default "false" the runner exports when the pass is unset', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    setE2EReduceMotionEnv('false');
    expect(isE2EReduceMotionMode()).toBe(false);
  });

  it('applyE2EReduceMotion forces the accessibility read on only when active', async () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');

    // Motion on (no reduce-motion var): the read is left untouched.
    setE2EReduceMotionEnv(undefined);
    (AccessibilityInfo as unknown as Record<string, unknown>)[
      'isReduceMotionEnabled'
    ] = () => Promise.resolve(false);
    applyE2EReduceMotion();
    await expect(AccessibilityInfo.isReduceMotionEnabled()).resolves.toBe(false);

    // Reduce-motion pass: the read is overridden to resolve true, the exact
    // signal the signature beats branch on for their no-motion path.
    setE2EReduceMotionEnv('true');
    applyE2EReduceMotion();
    await expect(AccessibilityInfo.isReduceMotionEnabled()).resolves.toBe(true);
  });
});

// ─── installE2EMockFetch gate ────────────────────────────────────────────────

describe('installE2EMockFetch', () => {
  it('does not replace globalThis.fetch when E2E mode is off', () => {
    setE2EEnv(undefined);
    const before = gThis['fetch'];
    installE2EMockFetch();
    expect(gThis['fetch']).toBe(before);
  });

  it('replaces globalThis.fetch when E2E mode is on', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    const before = gThis['fetch'];
    installE2EMockFetch();
    expect(gThis['fetch']).not.toBe(before);
  });
});

// ─── setupE2EMode ────────────────────────────────────────────────────────────

describe('setupE2EMode', () => {
  it('is a no-op when E2E mode is off', () => {
    setE2EEnv(undefined);
    const before = gThis['fetch'];
    setupE2EMode();
    expect(gThis['fetch']).toBe(before);
    expect(markOnboardingComplete).not.toHaveBeenCalled();
  });

  it('marks onboarding complete for the E2E user when mode is on', () => {
    gThis['__DEV__'] = true;
    setE2EEnv('true');
    setupE2EMode();
    expect(markOnboardingComplete).toHaveBeenCalledWith(E2E_SESSION.userId);
  });
});

// ─── e2eSessionStore ─────────────────────────────────────────────────────────

describe('e2eSessionStore', () => {
  it('loads the synthetic E2E session', async () => {
    const session = await e2eSessionStore.load();
    expect(session).toEqual(E2E_SESSION);
  });

  it('save is a no-op (does not change what load returns)', async () => {
    await e2eSessionStore.save(E2E_SESSION);
    const after = await e2eSessionStore.load();
    expect(after).toEqual(E2E_SESSION);
  });

  it('clear is a no-op (session persists for the process lifetime)', async () => {
    await e2eSessionStore.clear();
    const after = await e2eSessionStore.load();
    expect(after).toEqual(E2E_SESSION);
  });
});

// ─── e2eSessionStore × visual-review presets (FTY-247) ───────────────────────
//
// The session the store hydrates is a pure function of the active visual-review
// preset, so switching presets reseeds the session at runtime (the root layout
// remounts the SessionProvider on each activation). This is the regression guard
// for the signed-out preset being non-sticky: after activating `today.signed_out`
// a later signed-in preset must reload the synthetic session, not stay cleared.
describe('e2eSessionStore reflects the active visual-review preset', () => {
  afterEach(() => {
    __deactivateVisualReview();
  });

  it('loads a null session while the signed-out preset is active', async () => {
    expect(activateVisualReviewPreset('today.signed_out', null).ok).toBe(true);
    expect(await e2eSessionStore.load()).toBeNull();
  });

  it('reseeds the synthetic session when switching back to a signed-in preset', async () => {
    activateVisualReviewPreset('today.signed_out', null);
    expect(await e2eSessionStore.load()).toBeNull();

    // Runtime switch to a signed-in preset — order-independent, no rebuild.
    expect(activateVisualReviewPreset('today.populated', null).ok).toBe(true);
    expect(await e2eSessionStore.load()).toEqual(E2E_SESSION);
  });

  it('keeps the synthetic session for a signed-in preset', async () => {
    activateVisualReviewPreset('trends.populated', null);
    expect(await e2eSessionStore.load()).toEqual(E2E_SESSION);
  });
});

// ─── e2eConnectionStore ──────────────────────────────────────────────────────

describe('e2eConnectionStore', () => {
  it('loads the E2E server URL', async () => {
    const url = await e2eConnectionStore.load();
    expect(url).toBe(E2E_SERVER_URL);
  });

  it('save and clear are no-ops', async () => {
    await e2eConnectionStore.save('http://some-other-server.example');
    expect(await e2eConnectionStore.load()).toBe(E2E_SERVER_URL);

    await e2eConnectionStore.clear();
    expect(await e2eConnectionStore.load()).toBe(E2E_SERVER_URL);
  });
});

// ─── e2eCameraPermissionsHook ────────────────────────────────────────────────

describe('e2eCameraPermissionsHook', () => {
  it('reports camera access already granted so the scanner chrome renders', () => {
    const [permission] = e2eCameraPermissionsHook();
    expect(permission?.granted).toBe(true);
    expect(permission?.status).toBe('granted');
  });

  it('request and get resolve to the same granted response (never asks the OS)', async () => {
    const [permission, request, get] = e2eCameraPermissionsHook();
    await expect(request()).resolves.toEqual(permission);
    await expect(get()).resolves.toEqual(permission);
  });
});

// ─── createE2EMockFetch ───────────────────────────────────────────────────────

describe('createE2EMockFetch', () => {
  const mockFetch = createE2EMockFetch();
  const base = `${E2E_SERVER_URL}/api/users/${encodeURIComponent(E2E_SESSION.userId)}`;

  it('returns 404 for unknown endpoints', async () => {
    const res = await mockFetch(`${base}/unknown-endpoint`);
    expect(res.status).toBe(404);
  });

  it('accepts URL objects', async () => {
    const urlObj = new URL(`${base}/profile`);
    const res = await mockFetch(urlObj);
    expect(res.status).toBe(200);
  });
});

// ─── mock fetch ↔ real client alignment ──────────────────────────────────────
//
// Drift guard: instead of asserting the mock against hand-written suffixes, we
// drive the REAL API clients (the ones Today/Settings call on mount) through the
// mock. Each function builds its URL via `userScopedUrl`, so if a fixture suffix
// stops matching the real request path the mock 404s and the client throws —
// failing the test. This is what proves the fixtures serve the calls the app
// actually makes, and would have caught the `/goals/target` and
// `/log-events/today` mismatches.

describe('E2E mock serves the URLs the real API clients request', () => {
  const mockFetch = createE2EMockFetch();
  const apiSession = toApiSession(E2E_SESSION);

  it('getProfile resolves to the profile fixture', async () => {
    const profile = await getProfile(apiSession, mockFetch);
    expect(profile.user_id).toBe(E2E_SESSION.userId);
  });

  it('getTarget resolves to the target fixture', async () => {
    const target = await getTarget(apiSession, mockFetch);
    expect(target.calories.effective).toBe(2000);
  });

  // FTY-182 profile flow: saving a goal edit under the native header POSTs
  // /goal via the real createGoal client and must resolve to the reveal the
  // mini-target-reveal renders — proving the mock answers the goal create the
  // app actually makes (a 404 here would silently break the profile.yaml save).
  it('createGoal resolves to the goal + target reveal fixture', async () => {
    const reveal = await createGoal(
      apiSession,
      { direction: 'maintain' },
      mockFetch,
    );
    expect(reveal.goal.id).toBe(E2E_GOAL_TARGET_RESPONSE.goal.id);
    expect(reveal.target.calories).toBe(2000);
    expect(reveal.clamp.clamped).toBe(false);
  });

  // FTY-190 Settings flow: the cold-launched Goal row summarises the returning
  // user's real goal as direction + pace, both recovered from GET /goal (the
  // FTY-189/FTY-190 read model). The mock must answer the exact GET the real
  // getActiveGoal client makes, or the row falls back to the neutral "Details
  // unavailable" state settings-fty190.yaml would then fail on.
  it('getActiveGoal resolves to the seeded loss/steady goal', async () => {
    const goal = await getActiveGoal(apiSession, mockFetch);
    expect(goal).toEqual(E2E_ACTIVE_GOAL);
    expect(goal?.direction).toBe('loss');
    expect(goal?.pace).toBe('steady');
  });

  it('listTodayLogEvents resolves to an empty timeline (with the ?day= query)', async () => {
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(Array.isArray(events)).toBe(true);
    expect(events).toHaveLength(0);
  });

  it('listTodayLogEventEntries resolves to an empty item-forward feed on the empty day', async () => {
    // The Today screen reads the FTY-198 by-date feed alongside the event list;
    // the fixture suffix must match the real `/log-events/by-date` URL the client
    // builds, or the mock 404s and this throws — the drift guard for the item feed.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(Array.isArray(entries)).toBe(true);
    expect(entries).toHaveLength(0);
  });

  it('getDailySummary resolves to the zero-intake fixture', async () => {
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(false);
    expect(summary.target?.calories.effective).toBe(2000);
  });

  // FTY-322 swipe-to-delete: the delete.yaml flow soft-voids a row via the real
  // deleteLogEvent client's DELETE. The mock must answer that exact DELETE with
  // a 204 (a 404 here would make the row appear undeletable on-device), and the
  // isolated mock instance below proves the void then empties the day read.
  it('deleteLogEvent resolves (204) and the void empties the delete flow read', async () => {
    const isolated = createE2EMockFetch();
    // Create the delete-flow entry, then soft-void it by id.
    await createLogEvent(apiSession, 'yogurt to delete', undefined, isolated);
    await expect(
      deleteLogEvent(
        apiSession,
        'e2e-delete-event-00000000-0000-0000-0000-000000000000',
        isolated,
      ),
    ).resolves.toBeUndefined();
    // After the void the entry and its item drop out of every read.
    const events = await listTodayLogEvents(apiSession, '2026-01-01', isolated);
    expect(events).toHaveLength(0);
    const entries = await listTodayLogEventEntries(
      apiSession,
      '2026-01-01',
      isolated,
    );
    expect(entries).toHaveLength(0);
    const summary = await getDailySummary(apiSession, '2026-01-01', isolated);
    expect(summary.has_intake).toBe(false);
  });

  // FTY-187 Trends reads: the weight series and the adherence range back the
  // trends.yaml flow. Both are anchored to the requested window so the data
  // always lands in range — assert entries return and their dates fall in it.
  it('listWeightEntries resolves to a series inside the requested window', async () => {
    const from = '2026-06-01';
    const to = '2026-06-29';
    const entries = await listWeightEntries(apiSession, from, to, mockFetch);
    expect(entries.length).toBeGreaterThan(1);
    for (const e of entries) {
      expect(e.effective_date >= from && e.effective_date <= to).toBe(true);
    }
    // The last entry sits on the window's end (the device's today).
    expect(entries[entries.length - 1]?.effective_date).toBe(to);
  });

  it('createWeightEntry echoes the submitted weight and date back', async () => {
    const created = await createWeightEntry(
      apiSession,
      74.2,
      '2026-06-29',
      mockFetch,
    );
    expect(created.weight_kg).toBe(74.2);
    expect(created.effective_date).toBe('2026-06-29');
  });

  it('getDailySummaryRange resolves to one summary per day in the window', async () => {
    const from = '2026-06-01';
    const to = '2026-06-29';
    const range = await getDailySummaryRange(apiSession, from, to, mockFetch);
    expect(range).toHaveLength(29);
    expect(range[0]?.date).toBe(from);
    expect(range[range.length - 1]?.date).toBe(to);
    // The card is data-present: the recent days carry a target and logged intake.
    expect(range.some((d) => d.has_intake && d.target !== null)).toBe(true);
  });
});

// ─── FTY-162 clarify-flow stateful mock ──────────────────────────────────────
//
// Proves the stateful phase transitions that the clarify.yaml Maestro flow
// relies on. Each test creates a fresh mock instance so phases do not leak.

describe('FTY-162 clarify-flow: stateful mock phase transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('phase 0 → POST /log-events returns needs_clarification event', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.id).toBe(E2E_CLARIFY_EVENT_ID);
    expect(created.status).toBe('needs_clarification');
    expect(created.raw_text).toBe(E2E_CLARIFY_EVENT.raw_text);
  });

  it('phase 1 → GET /log-events returns the needs_clarification event list', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // advance to phase 1
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_CLARIFY_EVENT_ID);
    expect(events[0]?.status).toBe('needs_clarification');
  });

  it('phase 1 → GET /clarification returns the seeded question, id, and chips', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // advance to phase 1
    const clarification = await getLogEventClarification(
      apiSession,
      E2E_CLARIFY_EVENT_ID,
      mockFetch,
    );
    expect(clarification.questions).toHaveLength(1);
    expect(clarification.questions[0]?.id).toBe(E2E_CLARIFY_QUESTION_ID);
    expect(clarification.questions[0]?.text).toBe(E2E_CLARIFY_QUESTION);
    // FTY-170 payload carries candidate quick-pick options the sheet renders as chips.
    expect(clarification.questions[0]?.options).toEqual(E2E_CLARIFY_OPTIONS);
  });

  it('phase 1 → POST /clarification/answers resolves the SAME event in place', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    const resolved = await answerClarification(
      apiSession,
      E2E_CLARIFY_EVENT_ID,
      E2E_CLARIFY_QUESTION_ID,
      'Large',
      mockFetch,
    ); // phase 1 → 2
    // Same entry, transitioned in place — no duplicate row (A5)…
    expect(resolved.id).toBe(E2E_CLARIFY_EVENT_ID);
    expect(resolved.status).toBe('processing');
    // …and the raw phrase is never mutated by an answer (A3): still "coffee".
    expect(resolved.raw_text).toBe('coffee');
  });

  it('phase 2 (after answer) → GET /log-events returns the SAME event, completed', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    await answerClarification(
      apiSession,
      E2E_CLARIFY_EVENT_ID,
      E2E_CLARIFY_QUESTION_ID,
      'Large',
      mockFetch,
    ); // phase 1 → 2
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    // One row: the clarify event itself, transitioned to completed. Same id (no
    // duplicate — A5), same raw phrase (never mutated by an answer — A3), same
    // created_at. This is what makes clarify.yaml's post-refresh assertions a
    // genuine end-to-end proof of same-entry resolution.
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_CLARIFY_EVENT_ID);
    expect(events[0]?.status).toBe('completed');
    expect(events[0]?.raw_text).toBe(E2E_CLARIFY_EVENT.raw_text);
    expect(events[0]?.created_at).toBe(E2E_CLARIFY_EVENT.created_at);
  });

  it('phase 2 (after answer) → GET /daily-summary returns non-zero intake', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    await answerClarification(
      apiSession,
      E2E_CLARIFY_EVENT_ID,
      E2E_CLARIFY_QUESTION_ID,
      'Large',
      mockFetch,
    ); // phase 1 → 2
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(true);
    expect(summary.intake.calories).toBe(120);
  });

  it('smoke flow: a second POST /log-events also advances to the resolved phase', async () => {
    // The FTY-178 smoke flow reaches phase 2 via a plain re-submission (no
    // clarify sheet), so the second-POST path must keep advancing the machine.
    // A re-submission genuinely creates a second event server-side, so this
    // route — and only this route — serves the distinct-id resolved fixture.
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    const resolved = await createLogEvent(apiSession, 'coffee large', undefined, mockFetch); // phase 1 → 2
    expect(resolved.id).toBe(E2E_RESOLVED_EVENT.id);
    expect(resolved.id).not.toBe(E2E_CLARIFY_EVENT_ID);
    expect(resolved.status).toBe('completed');
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_RESOLVED_EVENT.id);
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.intake.calories).toBe(120);
  });

  it('phase 0 smoke: no POST means GET /log-events still returns empty list', async () => {
    const mockFetch = createE2EMockFetch();
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(0);
  });

  // Drift guard for the FTY-174 Maestro assertion: the clarify flow's resolved
  // fixture is computed as today-at-11:14 *device local*, so the timeline's
  // cluster label must format to the exact string clarify.yaml asserts
  // on-device ("11:14 AM"), in whatever timezone the test host runs. If someone
  // moves the fixture instant, this fails here before the e2e job does.
  it('resolved fixture renders as the clarify.yaml time label in the local zone', () => {
    expect(formatWallClockTime(E2E_CLARIFY_RESOLVED_EVENT.created_at)).toBe(
      E2E_RESOLVED_EVENT_TIME_LABEL,
    );
  });
});

// ─── FTY-176 failed-parse-flow stateful mock ─────────────────────────────────
//
// Proves the failed-parse branch the failed-parse.yaml Maestro flow relies on,
// and that it stays independent of the clarify phase machine. Each test builds a
// fresh mock so state does not leak.

describe('FTY-176 failed-parse flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('first gibberish POST returns a failed event', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_FAILED_RAW_TEXT,
      'key-1',
      mockFetch,
    );
    expect(created.id).toBe(E2E_FAILED_EVENT.id);
    expect(created.status).toBe('failed');
  });

  it('GET after the failed POST lists the failed event (so a poll never drops it)', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_FAILED_RAW_TEXT, 'key-1', mockFetch);
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.status).toBe('failed');
  });

  it('a Retry POST returns a fresh pending attempt with a distinct id', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_FAILED_RAW_TEXT, 'key-1', mockFetch);
    const retried = await createLogEvent(
      apiSession,
      E2E_FAILED_RAW_TEXT,
      'key-2',
      mockFetch,
    );
    expect(retried.id).toBe(E2E_FAILED_RETRY_EVENT.id);
    expect(retried.id).not.toBe(E2E_FAILED_EVENT.id);
    expect(retried.status).toBe('pending');
    // GET now lists the pending attempt so the reconciled row survives a poll.
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_FAILED_RETRY_EVENT.id);
    expect(events[0]?.status).toBe('pending');
  });

  it('the failed-parse branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    // "coffee" still runs the clarify phase machine, untouched by the gibberish key.
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });
});

// ─── FTY-183 correction-flow stateful mock ───────────────────────────────────
//
// Proves the endpoints the correction.yaml Maestro flow relies on: the saved-food
// typeahead pick, the completed log event it resolves to, the Change-match
// candidate list, and the re-resolve commit. Driven through the real API clients
// so the fixture URLs stay aligned with what the app actually requests.

describe('FTY-183 correction flow: stateful mock endpoints', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('saved-food search returns the seeded food for a matching query', async () => {
    const mockFetch = createE2EMockFetch();
    const response = await searchSavedFoods(apiSession, 'Chicken', mockFetch);
    expect(response.items).toHaveLength(1);
    expect(response.items[0]?.id).toBe(E2E_SAVED_FOOD.id);
    expect(response.items[0]?.name).toBe(E2E_SAVED_FOOD.name);
  });

  it('saved-food search returns nothing for a non-matching query (isolated from other flows)', async () => {
    const mockFetch = createE2EMockFetch();
    const response = await searchSavedFoods(apiSession, 'coffee', mockFetch);
    expect(response.items).toHaveLength(0);
  });

  it('submitting the saved food resolves straight to a completed event', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_SAVED_FOOD.name,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_SAVED_FOOD_EVENT_ID);
    expect(created.status).toBe('completed');
    // GET keeps serving the completed event so the resolved row survives a poll.
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_SAVED_FOOD_EVENT_ID);
    expect(events[0]?.status).toBe('completed');
  });

  it('the saved-food branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_SAVED_FOOD.name, undefined, mockFetch);
    // "coffee" still opens the clarify phase machine independently.
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });

  it('Change-match lists the USDA candidate for the item', async () => {
    const mockFetch = createE2EMockFetch();
    const candidates = await listSourceCandidates(
      apiSession,
      E2E_SAVED_FOOD_ITEM_ID,
      undefined,
      mockFetch,
    );
    expect(candidates).toHaveLength(1);
    expect(candidates[0]?.source_ref).toBe(E2E_SOURCE_CANDIDATE.source_ref);
    expect(candidates[0]?.name).toBe(E2E_SOURCE_CANDIDATE.name);
  });

  it('re-resolve commits the same item with new provenance and recomputed calories', async () => {
    const mockFetch = createE2EMockFetch();
    const updated = await reResolveItem(
      apiSession,
      E2E_SAVED_FOOD_ITEM_ID,
      E2E_SOURCE_CANDIDATE.source_ref,
      mockFetch,
    );
    // Same id + log_event_id → reconciles onto the same timeline row (no duplicate)…
    expect(updated.id).toBe(E2E_SAVED_FOOD_ITEM_ID);
    expect(updated.log_event_id).toBe(E2E_SAVED_FOOD_EVENT_ID);
    // …honest new provenance, and a recomputed value distinct from the original 640.
    expect(updated.source?.label).toBe('USDA');
    expect(updated.calories).toBe(415);
    expect(updated.calories).not.toBe(E2E_SAVED_FOOD.calories);
  });

  // FTY-245 regression guard: the saved-food correction sheet's Portion
  // (amount) stepper PATCHes this same endpoint against the saved-food item's
  // derived-item id. Before this fix that PATCH fell through to the mock's
  // default 404 ("E2E fixture not found for this URL"), which the client
  // rendered as "We couldn't find that item." — this test fails again if that
  // regresses.
  it('a Portion PATCH on the saved-food item returns the recomputed item, not a 404', async () => {
    const mockFetch = createE2EMockFetch();
    const edited = await editDerivedItem(
      apiSession,
      'food',
      E2E_SAVED_FOOD_ITEM_ID,
      'quantity',
      1.25,
      mockFetch,
    );
    expect(edited.id).toBe(E2E_SAVED_FOOD_ITEM_ID);
    expect(edited.item_type).toBe('food');
    expect(edited).toEqual(E2E_SAVED_FOOD_EDITED_ITEM);
    if (edited.item_type === 'food') {
      expect(edited.calories).toBe(800);
      expect(edited.is_edited).toBe(false); // amount_adjust is provenance-preserving → item stays un-edited (contract)
    }
  });

  it('the saved-food Portion PATCH branch does not disturb the estimated-correction PATCH branch', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_CORRECTION_RAW_TEXT, undefined, mockFetch);
    const edited = await editDerivedItem(
      apiSession,
      'food',
      E2E_CORRECTION_ITEM_ID,
      'quantity',
      1.25,
      mockFetch,
    );
    expect(edited).toEqual(E2E_CORRECTION_EDITED_ITEM);
  });
});

// ─── FTY-183 weight save/refetch stateful mock ───────────────────────────────
//
// The trends.yaml flow logs a weight, then asserts the refetched Trends headline
// reflects it. That only works if a POST records the weight and a subsequent GET
// upserts today's point to it — proven here through the real weight clients.

describe('FTY-183 weight flow: a save upserts the refetched series', () => {
  const apiSession = toApiSession(E2E_SESSION);
  const to = '2026-06-29';

  it('GET before any save leaves the window-end point at its seeded value', async () => {
    const mockFetch = createE2EMockFetch();
    const entries = await listWeightEntries(apiSession, '2026-06-01', to, mockFetch);
    const last = entries[entries.length - 1];
    expect(last?.effective_date).toBe(to);
    // The seeded series ends at 74.8 kg (the freshest point), not the saved value.
    expect(last?.weight_kg).toBe(74.8);
  });

  it('after a save, GET upserts the window-end point to the saved weight', async () => {
    const mockFetch = createE2EMockFetch();
    await createWeightEntry(apiSession, 70, to, mockFetch);
    const entries = await listWeightEntries(apiSession, '2026-06-01', to, mockFetch);
    const last = entries[entries.length - 1];
    expect(last?.effective_date).toBe(to);
    // The refetched series carries the just-saved weight — the load-bearing
    // signal behind trends.yaml's recomputed "74.7 kg" headline assertion.
    expect(last?.weight_kg).toBe(70);
  });
});

// ─── FTY-181 entry-resolve-flow stateful mock ────────────────────────────────
//
// Proves the resolve.yaml Maestro flow's data path: a log resolves to a completed
// pending entry whose real derived items ride the item-forward by-date feed once
// the event list refreshes, so the entry-resolve beat and secondary item-row
// path are reachable on the real screen data. Keyed on its own raw_text,
// independent of the clarify and failed phase machines.

describe('FTY-181 entry-resolve flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('POST the resolve text returns a pending entry first', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_RESOLVE_RAW_TEXT,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_RESOLVE_EVENT_ID);
    expect(created.status).toBe('pending');
  });

  it('the event list and by-date feed carry the completed multi-item entry after refresh', async () => {
    const mockFetch = createE2EMockFetch();
    // Before the log the item-forward feed is empty (empty day).
    expect(
      await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch),
    ).toHaveLength(0);
    await createLogEvent(apiSession, E2E_RESOLVE_RAW_TEXT, undefined, mockFetch);
    // After the log, refresh/poll sees the same event completed while the feed
    // carries two derived items. Today keeps the first item on the event-keyed
    // resolve row and then restores the second item as its own row.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(1);
    expect(entries[0]?.event.id).toBe(E2E_RESOLVE_EVENT_ID);
    expect(entries[0]?.items).toHaveLength(2);
    expect(entries[0]?.items[0]?.name).toBe(E2E_RESOLVE_ITEM.name);
    // The plain event list also lists the completed entry so a Refresh/poll keeps
    // the reconciled row while its items ride the feed above.
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_RESOLVE_EVENT_ID);
    // The day totals count both resolved items.
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.intake.calories).toBe(245);
  });

  it('the resolve branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });
});

// ─── FTY-181 correction-saved (beat 2) flow stateful mock ────────────────────
//
// Proves correction-beat.yaml's data path: the log resolves to a tappable resolved
// row on the by-date feed, and a PATCH to that item returns the server-recomputed
// value the correction-saved beat rides. Keyed on its own raw_text, independent
// of the resolve / clarify / failed machines.

describe('FTY-181 correction-saved flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('POST the correction text returns a completed entry with a tappable row', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_CORRECTION_RAW_TEXT,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_CORRECTION_EVENT_ID);
    expect(created.status).toBe('completed');
    // The by-date feed carries the resolved item the correction sheet opens on.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(1);
    const item = entries[0]?.items[0];
    expect(item?.id).toBe(E2E_CORRECTION_ITEM_ID);
    expect(item?.item_type).toBe('food');
    if (item?.item_type === 'food') {
      expect(item.calories).toBe(E2E_CORRECTION_ITEM.calories);
    }
  });

  it('a PATCH to the item returns the server-recomputed value the beat rides', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_CORRECTION_RAW_TEXT, undefined, mockFetch);
    // The amount step commits a single-field quantity PATCH; the mock echoes the
    // recomputed item (1.25 cups → 175 kcal, amount_adjust → is_edited false) —
    // the visible confirmation correction-beat.yaml asserts, proving the beat's commit path.
    const edited = await editDerivedItem(
      apiSession,
      'food',
      E2E_CORRECTION_ITEM_ID,
      'quantity',
      1.25,
      mockFetch,
    );
    expect(edited.id).toBe(E2E_CORRECTION_ITEM_ID);
    expect(edited.item_type).toBe('food');
    expect(edited).toEqual(E2E_CORRECTION_EDITED_ITEM);
    if (edited.item_type === 'food') {
      expect(edited.calories).toBe(175);
      expect(edited.is_edited).toBe(false);
    }
  });

  it('the correction branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });
});

// ─── FTY-181 target-reached (beat 3) flow stateful mock ──────────────────────
//
// Proves target.yaml's data path: the day starts at zero intake (hero under
// target → seeds not-reached), and a single large log flips the summary over the
// calorie target so the hero crosses into its over-budget state. Keyed on its own
// raw_text, independent of the other machines.

describe('FTY-181 target-reached flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('starts under target: the empty-day summary is zero intake', async () => {
    const mockFetch = createE2EMockFetch();
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(false);
    expect(summary.intake.calories).toBe(0);
    expect(summary.target?.calories.effective).toBe(2000);
  });

  it('POST the large text crosses the target: the summary lands over budget', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_TARGET_RAW_TEXT,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_TARGET_EVENT_ID);
    expect(created.status).toBe('completed');
    // The day summary now exceeds the 2,000-kcal target — the crossing that arms
    // beat 3 and drives the hero's over-budget end state target.yaml asserts.
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(true);
    expect(summary.intake.calories).toBe(2100);
    expect(summary.intake.calories).toBeGreaterThan(
      summary.target?.calories.effective ?? Infinity,
    );
    // The by-date feed carries the large item so the entry renders resolved.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    const item = entries[0]?.items[0];
    expect(item?.item_type).toBe('food');
    if (item?.item_type === 'food') {
      expect(item.calories).toBe(E2E_TARGET_ITEM.calories);
    }
  });

  it('the target branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });
});
