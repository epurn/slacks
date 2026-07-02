import { useEffect } from "react";
import { act, create } from "react-test-renderer";

import {
  GoalDirectionProvider,
  useGoalDirection,
  useGoalDirectionController,
  type GoalDirectionController,
} from "./goalDirection";
import type { GoalDirection } from "@/api/goals";
import type { GoalDirectionRecord, GoalDirectionStore } from "./goalDirectionStore";
import { SessionProvider } from "./session";
import type { SessionRecord } from "./session";
import type { SessionStore } from "./sessionStore";

const USER = "user-1";

/** A session store that hydrates a fixed signed-in user (or none). */
function sessionStoreFor(userId: string | null): SessionStore {
  const record: SessionRecord | null =
    userId === null
      ? null
      : { serverUrl: "https://fatty.example.test", token: "t.t", userId };
  return {
    save: jest.fn(async () => {}),
    load: jest.fn(async () => record),
    clear: jest.fn(async () => {}),
  };
}

/** A goal-direction store spy seeded with an optional persisted record. */
function goalStoreWith(record: GoalDirectionRecord | null): jest.Mocked<GoalDirectionStore> {
  return {
    save: jest.fn(async (_userId: string, _direction: GoalDirection): Promise<void> => {}),
    load: jest.fn(async (): Promise<GoalDirectionRecord | null> => record),
    clear: jest.fn(async (): Promise<void> => {}),
  };
}

// Captured hook values from the most recent render, held on a const object
// (not a reassigned free variable) so the render stays lint-clean.
const captured: { direction: string | null; controller: GoalDirectionController | null } = {
  direction: null,
  controller: null,
};

function Capture() {
  const direction = useGoalDirection();
  const controller = useGoalDirectionController();
  useEffect(() => {
    captured.direction = direction;
    captured.controller = controller;
  });
  return null;
}

describe("useGoalDirection — no provider", () => {
  it("returns null (never throws) when no provider is mounted", () => {
    act(() => {
      create(<Capture />);
    });
    expect(captured.direction).toBeNull();
  });
});

describe("GoalDirectionProvider", () => {
  it("starts with no known direction", () => {
    act(() => {
      create(
        <GoalDirectionProvider>
          <Capture />
        </GoalDirectionProvider>,
      );
    });
    expect(captured.direction).toBeNull();
  });

  it("setGoalDirection updates the value every consumer reads", () => {
    act(() => {
      create(
        <GoalDirectionProvider>
          <Capture />
        </GoalDirectionProvider>,
      );
    });
    act(() => {
      captured.controller!.setGoalDirection("gain");
    });
    expect(captured.direction).toBe("gain");
  });

  it("clearGoalDirection resets to null (e.g. on sign-out)", () => {
    act(() => {
      create(
        <GoalDirectionProvider>
          <Capture />
        </GoalDirectionProvider>,
      );
    });
    act(() => {
      captured.controller!.setGoalDirection("loss");
    });
    expect(captured.direction).toBe("loss");
    act(() => {
      captured.controller!.clearGoalDirection();
    });
    expect(captured.direction).toBeNull();
  });
});

describe("GoalDirectionProvider — on-device persistence (FTY-189)", () => {
  beforeEach(() => {
    captured.direction = null;
    captured.controller = null;
  });

  it("hydrates the persisted direction for the signed-in user on launch", async () => {
    const goalStore = goalStoreWith({ userId: USER, direction: "gain" });
    await act(async () => {
      create(
        <SessionProvider store={sessionStoreFor(USER)}>
          <GoalDirectionProvider store={goalStore}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });
    // A returning gain-goal user is fed their real direction, not the loss default.
    expect(captured.direction).toBe("gain");
  });

  it("ignores a persisted record belonging to a different account", async () => {
    const goalStore = goalStoreWith({ userId: "someone-else", direction: "gain" });
    await act(async () => {
      create(
        <SessionProvider store={sessionStoreFor(USER)}>
          <GoalDirectionProvider store={goalStore}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });
    expect(captured.direction).toBeNull();
  });

  it("does not hydrate when there is no persisted record", async () => {
    const goalStore = goalStoreWith(null);
    await act(async () => {
      create(
        <SessionProvider store={sessionStoreFor(USER)}>
          <GoalDirectionProvider store={goalStore}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });
    expect(captured.direction).toBeNull();
  });

  it("persists a newly set direction under the signed-in user", async () => {
    const goalStore = goalStoreWith(null);
    await act(async () => {
      create(
        <SessionProvider store={sessionStoreFor(USER)}>
          <GoalDirectionProvider store={goalStore}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });
    await act(async () => {
      captured.controller!.setGoalDirection("maintain");
    });
    expect(captured.direction).toBe("maintain");
    expect(goalStore.save).toHaveBeenCalledWith(USER, "maintain");
  });

  it("does not clobber a direction set this session with the persisted one", async () => {
    // A deferred load lets us set a fresh value while hydration is still pending.
    let resolveLoad!: (r: GoalDirectionRecord | null) => void;
    const goalStore = goalStoreWith(null);
    goalStore.load.mockImplementation(
      () =>
        new Promise<GoalDirectionRecord | null>((resolve) => {
          resolveLoad = resolve;
        }),
    );
    await act(async () => {
      create(
        <SessionProvider store={sessionStoreFor(USER)}>
          <GoalDirectionProvider store={goalStore}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });
    // Set a fresh value, then let the (older) persisted read resolve.
    act(() => {
      captured.controller!.setGoalDirection("gain");
    });
    await act(async () => {
      resolveLoad({ userId: USER, direction: "loss" });
    });
    expect(captured.direction).toBe("gain");
  });
});
