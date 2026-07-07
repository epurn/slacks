import { useState } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { useOfflineQueue, type OfflineQueue } from "./useOfflineQueue";
import {
  outboxOwnerKey,
  type OutboxEntry,
  type OutboxOwner,
  type OutboxStore,
} from "./outbox";
import type { LogEventDTO } from "@/api/logEvents";

const USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const SERVER_1 = "https://one.example.test";
const SERVER_2 = "https://two.example.test";

// Owner = server URL + user id (FTY-277). OWNER_A and OWNER_A2 are the *same*
// user id on two different self-hosted servers — two distinct owners.
const OWNER_A: OutboxOwner = { serverUrl: SERVER_1, userId: USER_A };
const OWNER_B: OutboxOwner = { serverUrl: SERVER_1, userId: USER_B };
const OWNER_A2: OutboxOwner = { serverUrl: SERVER_2, userId: USER_A };

function entry(overrides: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    idempotencyKey: "key-a",
    userId: USER_A,
    rawText: "two eggs",
    capturedAt: "2026-06-28T08:00:00Z",
    syncState: "queued",
    ...overrides,
  };
}

function serverEvent(id: string): LogEventDTO {
  return {
    id,
    user_id: USER_A,
    raw_text: "two eggs",
    status: "pending",
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
  };
}

/**
 * A controllable in-memory store keyed by the full owner key (server + user),
 * recording its calls. `save([])` removes the record, mirroring the real store's
 * residue cleanup.
 */
function makeStore(initial: Record<string, readonly OutboxEntry[]> = {}) {
  const data = new Map<string, readonly OutboxEntry[]>(Object.entries(initial));
  const cleared: string[] = [];
  const store: OutboxStore = {
    load: jest.fn(async (owner: OutboxOwner) => data.get(outboxOwnerKey(owner)) ?? []),
    save: jest.fn(async (owner: OutboxOwner, entries: readonly OutboxEntry[]) => {
      if (entries.length === 0) data.delete(outboxOwnerKey(owner));
      else data.set(outboxOwnerKey(owner), entries);
    }),
    clear: jest.fn(async (owner: OutboxOwner) => {
      cleared.push(outboxOwnerKey(owner));
      data.delete(outboxOwnerKey(owner));
    }),
  };
  return { store, cleared, data };
}

/** Seed a store record under an owner's key. */
function seed(
  owner: OutboxOwner,
  entries: readonly OutboxEntry[],
): Record<string, readonly OutboxEntry[]> {
  return { [outboxOwnerKey(owner)]: entries };
}

// Every tree created in a test, torn down in afterEach so a prior test's still-
// mounted hook can't fire a late setState (its drain/interval) outside the next
// test's act() and spam "update not wrapped in act" warnings.
const liveTrees: ReactTestRenderer[] = [];

afterEach(() => {
  act(() => {
    for (const tree of liveTrees.splice(0)) tree.unmount();
  });
});

/**
 * Renders the hook in a throwaway host component and exposes its latest return
 * value, plus a setter to drive an owner transition (A → null → A/B).
 */
function renderQueue(opts: {
  initialOwner: OutboxOwner | null;
  store: OutboxStore;
  submit?: (entry: OutboxEntry) => Promise<LogEventDTO>;
  onAccepted?: (entry: OutboxEntry, event: LogEventDTO) => void;
}) {
  let latest!: OfflineQueue;
  let setOwner!: (owner: OutboxOwner | null) => void;

  function Host(props: { initialOwner: OutboxOwner | null }) {
    const [owner, setId] = useState(props.initialOwner);
    setOwner = setId;
    latest = useOfflineQueue({
      owner,
      store: opts.store,
      submit:
        opts.submit ??
        (async () => {
          throw new Error("submit not expected in this test");
        }),
      onAccepted: opts.onAccepted ?? (() => {}),
    });
    return null;
  }

  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(<Host initialOwner={opts.initialOwner} />);
  });
  liveTrees.push(tree);
  return {
    get current() {
      return latest;
    },
    setOwner: (owner: OutboxOwner | null) =>
      act(() => {
        setOwner(owner);
      }),
    unmount: () =>
      act(() => {
        const i = liveTrees.indexOf(tree);
        if (i >= 0) liveTrees.splice(i, 1);
        tree.unmount();
      }),
  };
}

// Let the async store.load()/save() promise chains settle inside act(), so the
// setState they trigger is wrapped and React emits no "not wrapped in act"
// warning. setImmediate drains the full microtask queue for the pending chain.
async function flush() {
  await act(async () => {
    await new Promise<void>((resolve) => setImmediate(() => resolve()));
  });
}

describe("useOfflineQueue — sign-out persistence (FTY-277)", () => {
  it("keeps the durable queue on sign-out and reloads it when the same owner returns", async () => {
    // This covers both a manual Settings sign-out and an FTY-274 authenticated
    // 401 clear: both funnel through the session dropping to null, which the
    // hook sees as owner → null.
    const { store, cleared, data } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store });
    await flush();
    expect(harness.current.entries).toHaveLength(1);
    expect(harness.current.reachability).toBe("offline");

    // Sign out: the queue is hidden (memory cleared, calm online surface) but the
    // durable file is NOT deleted — no store.clear, the record is still on disk.
    harness.setOwner(null);
    await flush();
    expect(harness.current.entries).toEqual([]);
    expect(harness.current.reachability).toBe("online");
    expect(cleared).toEqual([]);
    expect(data.get(outboxOwnerKey(OWNER_A))).toHaveLength(1);

    // The same owner signs back in: their backlog reloads and drains as before.
    harness.setOwner(OWNER_A);
    await flush();
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual(["key-a"]);
    expect(harness.current.reachability).toBe("offline");
  });

  it("does not expose or drain the previous owner's entries while signed out", async () => {
    const submit = jest.fn();
    const { store } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();

    harness.setOwner(null);
    await flush();

    // The signed-out surface is empty/online and a drain finds no work.
    expect(harness.current.entries).toEqual([]);
    act(() => harness.current.drainNow());
    await flush();
    expect(submit).not.toHaveBeenCalled();
  });
});

describe("useOfflineQueue — owner isolation (FTY-277)", () => {
  it("switching to a different user shows only their backlog and never clears the previous owner's file", async () => {
    const { store, cleared, data } = makeStore({
      ...seed(OWNER_A, [entry()]),
      ...seed(OWNER_B, [entry({ userId: USER_B, idempotencyKey: "key-b" })]),
    });
    const harness = renderQueue({ initialOwner: OWNER_A, store });
    await flush();

    harness.setOwner(OWNER_B);
    await flush();

    // B sees only B's backlog; A's memory was evicted and A's file is untouched.
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual(["key-b"]);
    expect(cleared).toEqual([]);
    expect(data.get(outboxOwnerKey(OWNER_A))).toHaveLength(1);
  });

  it("never drains the previous user's entries after a switch", async () => {
    const submit = jest.fn();
    const { store } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();

    harness.setOwner(OWNER_B);
    await flush();

    act(() => harness.current.drainNow());
    await flush();
    expect(submit).not.toHaveBeenCalled();
  });

  it("does not share a queue between the same user id on two different servers", async () => {
    const submit = jest.fn();
    // Only server 1 has a backlog for this user id; server 2 has nothing.
    const { store, cleared, data } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();
    expect(harness.current.entries).toHaveLength(1);

    // Sign in to a *different* server with the SAME user id.
    harness.setOwner(OWNER_A2);
    await flush();

    // Server 2 sees no backlog, server 1's file is not cleared or drained.
    expect(harness.current.entries).toEqual([]);
    act(() => harness.current.drainNow());
    await flush();
    expect(submit).not.toHaveBeenCalled();
    expect(cleared).toEqual([]);
    expect(data.get(outboxOwnerKey(OWNER_A))).toHaveLength(1);
  });

  it("reloads A's backlog after switching A → B → A", async () => {
    const { store } = makeStore({
      ...seed(OWNER_A, [entry({ idempotencyKey: "a1" })]),
      ...seed(OWNER_B, [entry({ userId: USER_B, idempotencyKey: "b1" })]),
    });
    const harness = renderQueue({ initialOwner: OWNER_A, store });
    await flush();

    harness.setOwner(OWNER_B);
    await flush();
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual(["b1"]);

    harness.setOwner(OWNER_A);
    await flush();
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual(["a1"]);
  });

  it("aborts an in-flight drain when the owner switches, never submitting the previous user's remaining entries through the new session", async () => {
    // A submit that blocks on the first entry so the drain is still in flight
    // when the owner switches out from under it.
    let resolveSubmit!: (event: LogEventDTO) => void;
    const submitted: string[] = [];
    const submit = jest.fn((e: OutboxEntry) => {
      submitted.push(e.idempotencyKey);
      return new Promise<LogEventDTO>((resolve) => {
        resolveSubmit = resolve;
      });
    });
    const { store, data } = makeStore(
      seed(OWNER_A, [
        entry({ idempotencyKey: "a1" }),
        entry({ idempotencyKey: "a2" }),
      ]),
    );
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();

    // A's drain starts and blocks submitting a1; a2 is still queued behind it.
    act(() => harness.current.drainNow());
    await flush();
    expect(submitted).toEqual(["a1"]);

    // Switch to a *different* user while a1's submit is still in flight.
    harness.setOwner(OWNER_B);
    await flush();

    // a1's blocked submit now resolves. The drain must stop here: a2 is never
    // submitted, so A's remaining capture can't be sent through B's session.
    await act(async () => {
      resolveSubmit(serverEvent("a1"));
    });
    await flush();
    expect(submitted).toEqual(["a1"]);

    // The hook shows B's (empty) surface, not A's entries.
    expect(harness.current.entries).toEqual([]);

    // A's durable queue keeps a2 for A's own next sign-in (the accepted a1 has
    // left it); nothing leaked into a B record.
    expect(
      (data.get(outboxOwnerKey(OWNER_A)) ?? []).map((e) => e.idempotencyKey),
    ).toEqual(["a2"]);
    expect(data.get(outboxOwnerKey(OWNER_B))).toBeUndefined();

    // Signing back in as A reloads exactly the preserved remainder.
    harness.setOwner(OWNER_A);
    await flush();
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual(["a2"]);
  });

  it("aborts an in-flight drain on sign-out, preserving the owner's remaining entries without draining them", async () => {
    let resolveSubmit!: (event: LogEventDTO) => void;
    const submitted: string[] = [];
    const submit = jest.fn((e: OutboxEntry) => {
      submitted.push(e.idempotencyKey);
      return new Promise<LogEventDTO>((resolve) => {
        resolveSubmit = resolve;
      });
    });
    const { store, cleared, data } = makeStore(
      seed(OWNER_A, [
        entry({ idempotencyKey: "a1" }),
        entry({ idempotencyKey: "a2" }),
      ]),
    );
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();

    act(() => harness.current.drainNow());
    await flush();
    expect(submitted).toEqual(["a1"]);

    // Sign out (owner → null, as both a manual sign-out and an FTY-274 401 clear
    // funnel through) while a1's submit is in flight.
    harness.setOwner(null);
    await flush();
    await act(async () => {
      resolveSubmit(serverEvent("a1"));
    });
    await flush();

    // The remaining entry a2 is never submitted while signed out, the surface is
    // empty/online, and the durable file is preserved (never cleared) with a2.
    expect(submitted).toEqual(["a1"]);
    expect(harness.current.entries).toEqual([]);
    expect(harness.current.reachability).toBe("online");
    expect(cleared).toEqual([]);
    expect(
      (data.get(outboxOwnerKey(OWNER_A)) ?? []).map((e) => e.idempotencyKey),
    ).toEqual(["a2"]);
  });

  it("does not clear the durable queue on unmount (navigation away)", async () => {
    const { store, cleared } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store });
    await flush();

    harness.unmount();
    expect(cleared).toEqual([]);
  });
});

describe("useOfflineQueue — drain cleanup", () => {
  it("removes the durable record once a drain empties the queue", async () => {
    const submit = jest.fn(async () => serverEvent("key-a"));
    const { store, data } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();
    expect(data.get(outboxOwnerKey(OWNER_A))).toHaveLength(1);

    act(() => harness.current.drainNow());
    await flush();

    // The only entry was accepted → the queue empties and its file is removed,
    // leaving no residue (save(owner, []) deletes the record).
    expect(harness.current.entries).toEqual([]);
    expect(harness.current.reachability).toBe("online");
    expect(data.get(outboxOwnerKey(OWNER_A))).toBeUndefined();
  });
});

describe("useOfflineQueue enqueue/drain race", () => {
  it("keeps an entry captured during an in-flight drain (memory and store)", async () => {
    // A submit that blocks until we resolve it, so the drain stays in flight
    // while a new capture is enqueued underneath it.
    let resolveSubmit!: (event: LogEventDTO) => void;
    const submit = jest.fn(
      () =>
        new Promise<LogEventDTO>((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    const { store, data } = makeStore(seed(OWNER_A, [entry()]));
    const harness = renderQueue({ initialOwner: OWNER_A, store, submit });
    await flush();

    // Drain starts and blocks on the in-flight submit for key-a.
    act(() => harness.current.drainNow());
    await flush();
    expect(submit).toHaveBeenCalledTimes(1);

    // A fresh capture lands while that drain is still in flight.
    await act(async () => {
      await harness.current.enqueue(
        entry({ idempotencyKey: "key-b", rawText: "an apple" }),
      );
    });

    // The in-flight submit now resolves — key-a is accepted and leaves the queue.
    await act(async () => {
      resolveSubmit(serverEvent("key-a"));
    });
    await flush();

    // The drain snapshotted the queue before key-b existed; the fix merges
    // key-b back in rather than overwriting, so it survives in memory AND on
    // disk. Without it, key-b's raw capture would be silently dropped — the
    // exact data loss this feature exists to prevent.
    expect(harness.current.entries.map((e) => e.idempotencyKey)).toEqual([
      "key-b",
    ]);
    expect((data.get(outboxOwnerKey(OWNER_A)) ?? []).map((e) => e.idempotencyKey)).toEqual([
      "key-b",
    ]);
  });
});
