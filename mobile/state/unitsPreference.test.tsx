import { useEffect } from "react";
import { act, create } from "react-test-renderer";

import {
  UnitsPreferenceProvider,
  useUnitsPreference,
  useUnitsPreferenceController,
  type UnitsPreferenceController,
} from "./unitsPreference";
import { SessionProvider, type SessionRecord } from "@/state/session";
import type { SessionStore } from "@/state/sessionStore";
import type { UnitsPreference } from "@/state/profile";

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
const captured: {
  units: UnitsPreference | null;
  controller: UnitsPreferenceController | null;
} = {
  units: null,
  controller: null,
};

function Capture() {
  const units = useUnitsPreference();
  const controller = useUnitsPreferenceController();
  useEffect(() => {
    captured.units = units;
    captured.controller = controller;
  });
  return null;
}

describe("useUnitsPreference — no provider", () => {
  it("returns the metric default (never throws) when no provider is mounted", () => {
    act(() => {
      create(<Capture />);
    });
    expect(captured.units).toBe("metric");
  });
});

describe("UnitsPreferenceProvider", () => {
  it("starts on the metric default before any value is known", () => {
    act(() => {
      create(
        <UnitsPreferenceProvider>
          <Capture />
        </UnitsPreferenceProvider>,
      );
    });
    expect(captured.units).toBe("metric");
  });

  it("setUnitsPreference updates the value every consumer reads", () => {
    act(() => {
      create(
        <UnitsPreferenceProvider>
          <Capture />
        </UnitsPreferenceProvider>,
      );
    });
    act(() => {
      captured.controller!.setUnitsPreference("imperial");
    });
    expect(captured.units).toBe("imperial");
  });

  it("clearUnitsPreference resets to the metric default (e.g. on sign-out)", () => {
    act(() => {
      create(
        <UnitsPreferenceProvider>
          <Capture />
        </UnitsPreferenceProvider>,
      );
    });
    act(() => {
      captured.controller!.setUnitsPreference("imperial");
    });
    expect(captured.units).toBe("imperial");
    act(() => {
      captured.controller!.clearUnitsPreference();
    });
    expect(captured.units).toBe("metric");
  });
});

describe("UnitsPreferenceProvider — authoritative hydration (FTY-410)", () => {
  it("hydrates the preference from the GET /profile read for a signed-in user", async () => {
    const reader = jest.fn(async (): Promise<UnitsPreference> => "imperial");
    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <UnitsPreferenceProvider readUnitsPreference={reader}>
            <Capture />
          </UnitsPreferenceProvider>
        </SessionProvider>,
      );
    });

    // A returning imperial user is known after a cold launch, without any
    // in-session Settings save — the fix for the always-metric Trends render.
    expect(reader).toHaveBeenCalledTimes(1);
    expect(captured.units).toBe("imperial");
  });

  it("does not call the read when there is no signed-in session", async () => {
    const reader = jest.fn(async (): Promise<UnitsPreference> => "imperial");
    await act(async () => {
      create(
        <SessionProvider store={sessionStore(null)}>
          <UnitsPreferenceProvider readUnitsPreference={reader}>
            <Capture />
          </UnitsPreferenceProvider>
        </SessionProvider>,
      );
    });

    expect(reader).not.toHaveBeenCalled();
    expect(captured.units).toBe("metric");
  });

  it("falls back to the metric default when the read is unreachable", async () => {
    const reader = jest.fn(async (): Promise<UnitsPreference> => {
      throw new Error("offline");
    });
    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <UnitsPreferenceProvider readUnitsPreference={reader}>
            <Capture />
          </UnitsPreferenceProvider>
        </SessionProvider>,
      );
    });

    expect(reader).toHaveBeenCalledTimes(1);
    expect(captured.units).toBe("metric");
  });

  it("never clobbers a fresher same-session set with a slower hydrate", async () => {
    // The read resolves only when we release it, simulating a slow GET /profile
    // that lands *after* the user changed units in Settings this session.
    let release: (u: UnitsPreference) => void = () => {};
    const pending = new Promise<UnitsPreference>((resolve) => {
      release = resolve;
    });
    const reader = jest.fn(() => pending);

    await act(async () => {
      create(
        <SessionProvider store={sessionStore()}>
          <UnitsPreferenceProvider readUnitsPreference={reader}>
            <Capture />
          </UnitsPreferenceProvider>
        </SessionProvider>,
      );
    });

    // In-session Settings save wins first…
    act(() => {
      captured.controller!.setUnitsPreference("imperial");
    });
    expect(captured.units).toBe("imperial");

    // …and the older hydrate that resolves afterward must not overwrite it.
    await act(async () => {
      release("metric");
      await pending;
    });
    expect(captured.units).toBe("imperial");
  });
});
