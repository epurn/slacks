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
import { E2E_SESSION, E2E_SERVER_URL } from './fixtures';
// eslint-disable-next-line import/first
import { markOnboardingComplete } from '@/state/onboardingComplete';

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

  it('returns 200 with profile fixture for the profile endpoint', async () => {
    const res = await mockFetch(`${base}/profile`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { user_id: string };
    expect(body.user_id).toBe(E2E_SESSION.userId);
  });

  it('returns 200 with [] for today log events', async () => {
    const res = await mockFetch(`${base}/log-events/today`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as unknown[];
    expect(Array.isArray(body)).toBe(true);
    expect(body).toHaveLength(0);
  });

  it('returns 200 with zero summary for daily-summary', async () => {
    const res = await mockFetch(`${base}/daily-summary`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { has_intake: boolean };
    expect(body.has_intake).toBe(false);
  });

  it('returns 200 with target fixture for goals/target', async () => {
    const res = await mockFetch(`${base}/goals/target`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { calories: { effective: number } };
    expect(body.calories.effective).toBe(2000);
  });

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
