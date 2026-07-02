import { useEffect } from "react";
import { act, create } from "react-test-renderer";

import {
  GoalDirectionProvider,
  useGoalDirection,
  useGoalDirectionController,
  type GoalDirectionController,
} from "./goalDirection";

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
