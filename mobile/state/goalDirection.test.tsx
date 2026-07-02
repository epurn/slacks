import { useEffect } from "react";
import { act, create } from "react-test-renderer";

import {
  GoalDirectionProvider,
  useGoalDirection,
  useGoalDirectionController,
  type GoalDirectionController,
} from "./goalDirection";
import { SessionProvider, type SessionRecord } from "@/state/session";
import type { SessionStore } from "@/state/sessionStore";
import type { GoalDirection } from "@/api/goals";

const RECORD: SessionRecord = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

/** A session store that hydrates a signed-in session (or none). */
function sessionStore(initial: SessionRecord | null = RECORD): SessionStore {
  let value = initial;
  return {
    load: async () => value,
    save: async (s: SessionRecord) => {
      value = s;
    },
    clear: async () => {
      value = null;
    },
  } satisfies SessionStore;
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

describe("GoalDirectionProvider — authoritative hydration (FTY-189)", () => {
  it("hydrates the direction from the GET /goal read for a signed-in user", async () => {
    const reader = jest.fn(async () => "gain" as GoalDirection);
    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <GoalDirectionProvider readActiveGoalDirection={reader}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });

    // A returning user with an existing gain goal is known after a cold launch,
    // without any in-session Settings/Onboarding save.
    expect(reader).toHaveBeenCalledTimes(1);
    expect(captured.direction).toBe("gain");
  });

  it("does not call the read when there is no signed-in session", async () => {
    const reader = jest.fn(async () => "loss" as GoalDirection);
    await act(async () => {
      create(
        <SessionProvider store={sessionStore(null)}>
          <GoalDirectionProvider readActiveGoalDirection={reader}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });

    expect(reader).not.toHaveBeenCalled();
    expect(captured.direction).toBeNull();
  });

  it("leaves the direction unknown (null) when the read reports no active goal", async () => {
    const reader = jest.fn(async () => null);
    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <GoalDirectionProvider readActiveGoalDirection={reader}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });

    expect(reader).toHaveBeenCalledTimes(1);
    expect(captured.direction).toBeNull();
  });

  it("never clobbers a fresher same-session set with a slower hydrate", async () => {
    // The read resolves only when we release it, simulating a slow GET /goal that
    // lands *after* the user created/edited a goal this session.
    let release: (d: GoalDirection) => void = () => {};
    const pending = new Promise<GoalDirection>((resolve) => {
      release = resolve;
    });
    const reader = jest.fn(() => pending);

    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <GoalDirectionProvider readActiveGoalDirection={reader}>
            <Capture />
          </GoalDirectionProvider>
        </SessionProvider>,
      );
    });

    // In-session save wins first…
    act(() => {
      captured.controller!.setGoalDirection("gain");
    });
    expect(captured.direction).toBe("gain");

    // …and the older hydrate that resolves afterward must not overwrite it.
    await act(async () => {
      release("loss");
      await pending;
    });
    expect(captured.direction).toBe("gain");
  });
});
