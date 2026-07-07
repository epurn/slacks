/**
 * Integration: the offline outbox survives an FTY-274 authenticated-401 session
 * clear and reloads for the same owner (FTY-277).
 *
 * This exercises the real seam end-to-end — `api/client`'s `notifyUnauthorized`
 * → `SessionProvider.signOut` → the session dropping to `null` → `useOfflineQueue`
 * seeing `owner → null` — rather than unit-testing the hook against a synthetic
 * transition, so it proves the 401 path (not just a manual sign-out) keeps the
 * durable queue and never purges it.
 */

import { useEffect } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

// Inject a fake session store below, so the real keychain is never touched; mock
// it inert to keep the import resolvable (as in session.test.tsx).
jest.mock("expo-secure-store", () => ({
  setItemAsync: async () => {},
  getItemAsync: async () => null,
  deleteItemAsync: async () => {},
}));

// eslint-disable-next-line import/first
import {
  SessionProvider,
  useSession,
  useSessionController,
  type AuthClient,
  type SessionRecord,
} from "./session";
// eslint-disable-next-line import/first
import type { SessionStore } from "./sessionStore";
// eslint-disable-next-line import/first
import {
  outboxOwnerKey,
  type OutboxEntry,
  type OutboxOwner,
  type OutboxStore,
} from "./outbox";
// eslint-disable-next-line import/first
import { useOfflineQueue, type OfflineQueue } from "./useOfflineQueue";
// eslint-disable-next-line import/first
import { notifyUnauthorized, setUnauthorizedHandler } from "@/api/client";

// The unauthorized handler is a module-level singleton in api/client; restore
// the safe no-op after each test so a torn-down provider can't leak a handler.
afterEach(() => {
  setUnauthorizedHandler(null);
});

const RECORD: SessionRecord = {
  serverUrl: "https://fatty.example.test",
  token: "header.signature",
  userId: "11111111-1111-1111-1111-111111111111",
};
const OWNER: OutboxOwner = { serverUrl: RECORD.serverUrl, userId: RECORD.userId };

function queuedEntry(): OutboxEntry {
  return {
    idempotencyKey: "queued-1",
    userId: RECORD.userId,
    rawText: "two eggs",
    capturedAt: "2026-07-07T08:00:00Z",
    syncState: "queued",
  };
}

function fakeSessionStore(initial: SessionRecord | null): SessionStore {
  let value = initial;
  return {
    save: jest.fn(async (s: SessionRecord) => {
      value = s;
    }),
    load: jest.fn(async () => value),
    clear: jest.fn(async () => {
      value = null;
    }),
  } satisfies SessionStore;
}

function fakeAuth(): AuthClient {
  return {
    createAccount: jest.fn(async (serverUrl: string) => ({ ...RECORD, serverUrl })),
    signIn: jest.fn(async (serverUrl: string) => ({ ...RECORD, serverUrl })),
  } satisfies AuthClient;
}

/** In-memory outbox store keyed by owner, tracking `clear` calls. */
function outboxStore(seed: readonly OutboxEntry[]) {
  const data = new Map<string, readonly OutboxEntry[]>();
  if (seed.length > 0) data.set(outboxOwnerKey(OWNER), seed);
  const cleared: string[] = [];
  const store: OutboxStore = {
    load: async (owner: OutboxOwner) => data.get(outboxOwnerKey(owner)) ?? [],
    save: async (owner: OutboxOwner, entries: readonly OutboxEntry[]) => {
      if (entries.length === 0) data.delete(outboxOwnerKey(owner));
      else data.set(outboxOwnerKey(owner), entries);
    },
    clear: async (owner: OutboxOwner) => {
      cleared.push(outboxOwnerKey(owner));
      data.delete(outboxOwnerKey(owner));
    },
  };
  return { store, data, cleared };
}

const captured: {
  controller: ReturnType<typeof useSessionController> | null;
  queue: OfflineQueue | null;
} = { controller: null, queue: null };

function Harness({ store }: { store: OutboxStore }) {
  const controller = useSessionController();
  const session = useSession();
  const queue = useOfflineQueue({
    owner: session
      ? { serverUrl: session.serverUrl, userId: session.userId }
      : null,
    submit: async () => {
      throw new Error("submit not expected in this test");
    },
    store,
    onAccepted: () => {},
  });
  useEffect(() => {
    captured.controller = controller;
    captured.queue = queue;
  });
  return null;
}

function ctrl(): ReturnType<typeof useSessionController> {
  if (captured.controller === null) throw new Error("controller not captured");
  return captured.controller;
}
function queue(): OfflineQueue {
  if (captured.queue === null) throw new Error("queue not captured");
  return captured.queue;
}

async function flush() {
  await act(async () => {
    await new Promise<void>((resolve) => setImmediate(() => resolve()));
  });
}

let liveTree: ReactTestRenderer | null = null;
afterEach(() => {
  act(() => {
    liveTree?.unmount();
    liveTree = null;
  });
  captured.controller = null;
  captured.queue = null;
});

it("keeps the outbox across a 401 clear and reloads it when the same owner signs back in", async () => {
  const sessionStore = fakeSessionStore(RECORD);
  const { store, data, cleared } = outboxStore([queuedEntry()]);

  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <SessionProvider store={sessionStore} authClient={fakeAuth()}>
        <Harness store={store} />
      </SessionProvider>,
    );
  });
  liveTree = tree;
  await flush();

  // Signed in as OWNER with a queued capture already on disk.
  expect(ctrl().session).toEqual(RECORD);
  expect(queue().entries.map((e) => e.idempotencyKey)).toEqual(["queued-1"]);

  // A 401 on an authenticated request clears the session (FTY-274).
  await act(async () => {
    notifyUnauthorized();
  });
  await flush();

  // Session gone, outbox hidden — but the durable file is intact (never cleared).
  expect(ctrl().session).toBeNull();
  expect(queue().entries).toEqual([]);
  expect(cleared).toEqual([]);
  expect(data.get(outboxOwnerKey(OWNER))).toHaveLength(1);

  // The same owner signs back in: the queued capture reloads.
  await act(async () => {
    await ctrl().signIn(RECORD.serverUrl, "alice@example.com", "a-good-password");
  });
  await flush();

  expect(ctrl().session).toEqual(RECORD);
  expect(queue().entries.map((e) => e.idempotencyKey)).toEqual(["queued-1"]);
});
