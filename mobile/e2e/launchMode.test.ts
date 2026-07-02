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
  e2eSessionStore,
  e2eConnectionStore,
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
  E2E_CLARIFY_EVENT,
  E2E_RESOLVED_EVENT,
  E2E_RESOLVED_EVENT_TIME_LABEL,
  E2E_FAILED_RAW_TEXT,
  E2E_FAILED_EVENT,
  E2E_FAILED_RETRY_EVENT,
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
import { getTarget } from '@/api/goals';
// eslint-disable-next-line import/first
import { listTodayLogEvents, createLogEvent, getLogEventClarification } from '@/api/logEvents';
// eslint-disable-next-line import/first
import { getDailySummary } from '@/api/dailySummary';

// jest-expo sets __DEV__ = true globally. Use globalThis so TypeScript is happy
// without needing @types/node (which the project excludes from "types").
const gThis = globalThis as Record<string, unknown>;

// Capture originals so each test can restore them in afterEach.
const ORIGINAL_DEV = gThis['__DEV__'] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;
const ORIGINAL_FETCH = gThis['fetch'] as typeof fetch;

afterEach(() => {
  gThis['__DEV__'] = ORIGINAL_DEV;
  gThis['fetch'] = ORIGINAL_FETCH;
  // Restore the original env value (undefined means the var was absent).
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env['EXPO_PUBLIC_FATTY_E2E'];
  } else {
    process.env['EXPO_PUBLIC_FATTY_E2E'] = ORIGINAL_E2E_ENV;
  }
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

  it('listTodayLogEvents resolves to an empty timeline (with the ?day= query)', async () => {
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(Array.isArray(events)).toBe(true);
    expect(events).toHaveLength(0);
  });

  it('getDailySummary resolves to the zero-intake fixture', async () => {
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(false);
    expect(summary.target?.calories.effective).toBe(2000);
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

  it('phase 1 → GET /clarification returns the seeded question', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // advance to phase 1
    const clarification = await getLogEventClarification(
      apiSession,
      E2E_CLARIFY_EVENT_ID,
      mockFetch,
    );
    expect(clarification.questions).toHaveLength(1);
    expect(clarification.questions[0]?.text).toBe(E2E_CLARIFY_QUESTION);
  });

  it('phase 1 → second POST /log-events returns resolved event', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    const resolved = await createLogEvent(apiSession, 'coffee large', undefined, mockFetch); // phase 1 → 2
    expect(resolved.id).toBe(E2E_RESOLVED_EVENT.id);
    expect(resolved.status).toBe('completed');
    expect(resolved.raw_text).toBe('coffee large');
  });

  it('phase 2 → GET /log-events returns the resolved event list', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    await createLogEvent(apiSession, 'coffee large', undefined, mockFetch); // phase 1 → 2
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_RESOLVED_EVENT.id);
    expect(events[0]?.status).toBe('completed');
  });

  it('phase 2 → GET /daily-summary returns non-zero intake', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, 'coffee', undefined, mockFetch); // phase 0 → 1
    await createLogEvent(apiSession, 'coffee large', undefined, mockFetch); // phase 1 → 2
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(true);
    expect(summary.intake.calories).toBe(120);
  });

  it('phase 0 smoke: no POST means GET /log-events still returns empty list', async () => {
    const mockFetch = createE2EMockFetch();
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(0);
  });

  // Drift guard for the FTY-174 Maestro assertion: the resolved fixture is
  // computed as today-at-11:14 *device local*, so the timeline's cluster label
  // must format to the exact string clarify.yaml asserts on-device ("11:14 AM"),
  // in whatever timezone the test host runs. If someone moves the fixture
  // instant, this fails here before the e2e job does.
  it('resolved fixture renders as the clarify.yaml time label in the local zone', () => {
    expect(formatWallClockTime(E2E_RESOLVED_EVENT.created_at)).toBe(
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
