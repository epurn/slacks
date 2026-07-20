/**
 * Settings → ACCOUNT & SERVER: the user-configurable API base URL (FTY-405).
 *
 * These run against the **real** `ConnectionProvider` and an in-memory
 * connection store, so a change is proven where it counts: after the switch,
 * `resolveApiBaseUrl()` — the synchronous accessor every API client calls — is
 * reading the newly-persisted value, not the build-time default. Only the
 * session controller and the router are mocked (the token store and navigation
 * are not this story's seam).
 *
 * Covered:
 *   - the row shows the live base URL and opens the editor prefilled
 *   - malformed input is rejected in place, without probing or touching the session
 *   - an unreachable address is rejected with named-host copy, session intact
 *   - a confirmed change clears the session *before* the new base URL goes live,
 *     repoints every API call, and routes to sign-in (no cross-server token reuse)
 *   - "Use default" returns the field to the default server address
 *   - re-saving the address already in use costs nothing
 */

import React from 'react';
import { AccessibilityInfo, ActionSheetIOS } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ThemeProvider } from '@/theme';
import { SettingsScreen } from './SettingsScreen';
import { DEFAULT_API_BASE_URL, resolveApiBaseUrl, setConnectedBaseUrl } from '@/api/config';
import type { ProbeResult } from '@/api/serverConnection';
import { ConnectionProvider } from '@/state/connection';
import type { ServerConnectionStore } from '@/state/serverConnectionStore';
import type { Session } from '@/state/session';
import type { TargetReadModel } from '@/api/dailySummary';
import type { ProfileDTO } from '@/api/profile';
import type { AppSettingsStore } from '@/state/appSettings';
import type { CadenceStore, NotificationsAdapter, WeighInCadence } from '@/state/reminderScheduler';

const CONNECTED_URL = 'https://home.example.test';
const NEW_URL = 'https://other.example.test';

const SESSION: Session = {
  serverUrl: CONNECTED_URL,
  token: 'test-token',
  userId: '11111111-1111-1111-1111-111111111111',
};

// ─────────────────────────────────────────────────────────────────────────────
// Mocks: router + session controller only (the connection seam stays real).
// ─────────────────────────────────────────────────────────────────────────────
const mockReplace = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: jest.fn(() => ({ push: jest.fn(), back: jest.fn(), replace: mockReplace })),
  useLocalSearchParams: jest.fn(() => ({})),
}));

/** Records the order of session/connection side effects so we can assert it. */
const calls: string[] = [];
const mockSignOut = jest.fn(async () => {
  calls.push('signOut');
});

jest.mock('@/state/session', () => {
  const original = jest.requireActual<typeof import('@/state/session')>('@/state/session');
  return {
    ...original,
    useSession: jest.fn(() => SESSION),
    useSessionController: jest.fn(() => ({
      session: SESSION,
      status: 'ready',
      signOut: mockSignOut,
      signIn: jest.fn(),
      createAccount: jest.fn(),
    })),
  };
});

jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);
jest.spyOn(ActionSheetIOS, 'showActionSheetWithOptions').mockImplementation(() => {});

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures / stubs
// ─────────────────────────────────────────────────────────────────────────────

const PROFILE: ProfileDTO = {
  user_id: SESSION!.userId,
  height_m: 1.75,
  weight_kg: 80,
  birth_year: 1990,
  metabolic_formula: 'mifflin_st_jeor_plus5',
  units_preference: 'metric',
  timezone: 'America/New_York',
  updated_at: '2026-06-28T00:00:00Z',
};

const TARGET: TargetReadModel = {
  calories: { effective: 1800, derived: 1800, source: 'derived' },
  protein_g: { effective: 128, derived: 128, source: 'derived' },
  carbs_g: { effective: 148, derived: 148, source: 'derived' },
  fat_g: { effective: 64, derived: 64, source: 'derived' },
};

const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

/** In-memory stand-in for the on-device connection file. */
function memoryConnectionStore(initial: string | null): ServerConnectionStore & {
  readonly saved: string | null;
} {
  let value = initial;
  return {
    get saved() {
      return value;
    },
    load: async () => value,
    save: async (baseUrl: string) => {
      calls.push(`connect:${baseUrl}`);
      value = baseUrl;
    },
    clear: async () => {
      value = null;
    },
  };
}

const settingsStore: AppSettingsStore = {
  getAppearance: jest.fn(async () => 'system' as const),
  setAppearance: jest.fn(async () => {}),
};

const cadenceStore: CadenceStore = {
  getCadence: jest.fn(async () => 'weekly' as WeighInCadence),
  setCadence: jest.fn(async () => {}),
  getLastWeighInDate: jest.fn(async () => null),
  setLastWeighInDate: jest.fn(async () => {}),
};

const notificationsAdapter: NotificationsAdapter = {
  requestPermission: jest.fn(async () => true),
  cancelAll: jest.fn(async () => {}),
  scheduleAt: jest.fn(async () => {}),
};

async function renderSettings(options: {
  store: ServerConnectionStore;
  probe?: ProbeResult;
  colorScheme?: 'light' | 'dark';
}): Promise<ReactTestRenderer> {
  const { store, probe = 'reachable', colorScheme = 'light' } = options;
  const probeFn = jest.fn(async () => probe);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>
        <ThemeProvider override={colorScheme}>
          <ConnectionProvider store={store}>
            <SettingsScreen
              session={SESSION}
              probeServerFn={probeFn}
              getProfileFn={jest.fn().mockResolvedValue(PROFILE)}
              getTargetFn={jest.fn().mockResolvedValue(TARGET)}
              putProfileFn={jest.fn().mockResolvedValue(PROFILE)}
              createGoalFn={jest.fn()}
              getActiveGoalFn={jest.fn().mockResolvedValue(null)}
              setTargetOverrideFn={jest.fn()}
              resetTargetOverrideFn={jest.fn()}
              settingsStore={settingsStore}
              cadenceStore={cadenceStore}
              notificationsAdapter={notificationsAdapter}
            />
          </ConnectionProvider>
        </ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  (tree as ReactTestRenderer & { probeFn: jest.Mock }).probeFn = probeFn;
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === 'string')
    .map((n) => n.props.children as string)
    .join(' ');
}

function findByLabel(tree: ReactTestRenderer, label: string) {
  return tree.root.find((n) => n.props.accessibilityLabel === label && !!n.props.onPress);
}

async function press(tree: ReactTestRenderer, label: string) {
  await act(async () => {
    findByLabel(tree, label).props.onPress();
  });
}

function urlInput(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) => n.props.accessibilityLabel === 'Server address' && typeof n.props.onChangeText === 'function',
  );
}

async function typeUrl(tree: ReactTestRenderer, value: string) {
  await act(async () => {
    urlInput(tree).props.onChangeText(value);
  });
}

beforeEach(() => {
  calls.length = 0;
  mockReplace.mockClear();
  mockSignOut.mockClear();
  setConnectedBaseUrl(null);
});

describe('Settings server address (FTY-405)', () => {
  it('shows the connected base URL and opens the editor prefilled with it', async () => {
    const tree = await renderSettings({ store: memoryConnectionStore(CONNECTED_URL) });

    expect(textContent(tree)).toContain(CONNECTED_URL);

    await press(tree, `Server: ${CONNECTED_URL}`);
    expect(urlInput(tree).props.value).toBe(CONNECTED_URL);
  });

  it('rejects a malformed address in place, without probing or touching the session', async () => {
    const tree = await renderSettings({ store: memoryConnectionStore(CONNECTED_URL) });
    const { probeFn } = tree as ReactTestRenderer & { probeFn: jest.Mock };

    await press(tree, `Server: ${CONNECTED_URL}`);
    await typeUrl(tree, 'not a url');
    await press(tree, 'Check server address');

    expect(textContent(tree)).toContain("That doesn't look like a valid server address.");
    expect(probeFn).not.toHaveBeenCalled();
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(resolveApiBaseUrl()).toBe(CONNECTED_URL);
  });

  it('rejects a non-http scheme without probing it', async () => {
    const tree = await renderSettings({ store: memoryConnectionStore(CONNECTED_URL) });
    const { probeFn } = tree as ReactTestRenderer & { probeFn: jest.Mock };

    await press(tree, `Server: ${CONNECTED_URL}`);
    await typeUrl(tree, 'javascript:alert(1)');
    await press(tree, 'Check server address');

    expect(textContent(tree)).toContain('Use an http:// or https:// address.');
    expect(probeFn).not.toHaveBeenCalled();
  });

  it('rejects an unreachable address with named-host copy and keeps the app usable', async () => {
    const store = memoryConnectionStore(CONNECTED_URL);
    const tree = await renderSettings({ store, probe: 'unreachable' });

    await press(tree, `Server: ${CONNECTED_URL}`);
    await typeUrl(tree, NEW_URL);
    await press(tree, 'Check server address');

    expect(textContent(tree)).toContain("Can't reach other.example.test");
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(store.saved).toBe(CONNECTED_URL);
    // Still pointed at the working server; the field is still editable.
    expect(resolveApiBaseUrl()).toBe(CONNECTED_URL);
    expect(urlInput(tree).props.editable).toBe(true);
  });

  it('confirming a change clears the session first, repoints every API call, and routes to sign-in', async () => {
    const store = memoryConnectionStore(CONNECTED_URL);
    const tree = await renderSettings({ store });

    await press(tree, `Server: ${CONNECTED_URL}`);
    await typeUrl(tree, NEW_URL);
    await press(tree, 'Check server address');

    // A destructive switch is confirmed, never implicit.
    expect(textContent(tree)).toContain('Switching signs you out');
    expect(mockSignOut).not.toHaveBeenCalled();

    await press(tree, 'Switch server and sign out');

    // Session dropped BEFORE the new base URL went live — the old server's
    // token can never ride along to the new host.
    expect(calls).toEqual(['signOut', `connect:${NEW_URL}`]);
    expect(store.saved).toBe(NEW_URL);
    // Every API client reads this accessor; it is now the persisted value.
    expect(resolveApiBaseUrl()).toBe(NEW_URL);
    expect(mockReplace).toHaveBeenCalledWith('/signin');
  });

  it('offers a way back to the default server address', async () => {
    const tree = await renderSettings({ store: memoryConnectionStore(CONNECTED_URL) });

    await press(tree, `Server: ${CONNECTED_URL}`);
    await press(tree, 'Use default server address');

    expect(urlInput(tree).props.value).toBe(DEFAULT_API_BASE_URL);
  });

  it('re-saving the address already in use costs neither a probe nor the session', async () => {
    const tree = await renderSettings({ store: memoryConnectionStore(CONNECTED_URL) });
    const { probeFn } = tree as ReactTestRenderer & { probeFn: jest.Mock };

    await press(tree, `Server: ${CONNECTED_URL}`);
    await press(tree, 'Check server address');

    expect(probeFn).not.toHaveBeenCalled();
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(mockReplace).not.toHaveBeenCalled();
    // Editor closed back to the row.
    expect(tree.root.findAll((n) => n.props.testID === 'server-url-edit-card')).toHaveLength(0);
  });

  it('draws the editor from the theme in both light and dark', async () => {
    const inputColor = async (colorScheme: 'light' | 'dark') => {
      const tree = await renderSettings({
        store: memoryConnectionStore(CONNECTED_URL),
        colorScheme,
      });
      await press(tree, `Server: ${CONNECTED_URL}`);
      expect(textContent(tree)).toContain('Changing your server signs you out');
      const flat = (urlInput(tree).props.style as { color?: string }[]).find((s) => s?.color);
      return flat?.color;
    };

    const light = await inputColor('light');
    const dark = await inputColor('dark');
    expect(light).toBeTruthy();
    expect(dark).toBeTruthy();
    expect(light).not.toBe(dark);
  });
});
