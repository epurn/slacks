/**
 * FTY-404: `useKeyboardInset` reports the live software-keyboard height so a
 * scroll container can inset its content by the real platform frame — never a
 * magic offset. Driven by capturing the `Keyboard` subscriptions the hook
 * registers and firing synthetic show/hide events at them.
 */

import { Keyboard, Text } from "react-native";
import { act, create as render } from "react-test-renderer";

import { useKeyboardInset } from "./useKeyboardInset";

type Handler = (event: { endCoordinates?: { height: number } }) => void;

function Probe() {
  const inset = useKeyboardInset();
  return <Text testID="inset">{String(inset)}</Text>;
}

function readInset(tree: ReturnType<typeof render>): string {
  return tree.root.findByProps({ testID: "inset" }).props.children as string;
}

describe("useKeyboardInset", () => {
  let subs: Array<{ event: string; cb: Handler }>;

  beforeEach(() => {
    subs = [];
    jest
      .spyOn(Keyboard, "addListener")
      .mockImplementation((event: string, cb: unknown) => {
        subs.push({ event, cb: cb as Handler });
        return { remove: jest.fn() } as never;
      });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("starts at 0 and reports the keyboard height on show, back to 0 on hide", () => {
    let tree!: ReturnType<typeof render>;
    act(() => {
      tree = render(<Probe />);
    });

    // The hook registers the show subscription first, then the hide one.
    expect(subs).toHaveLength(2);
    const [show, hide] = subs;

    expect(readInset(tree)).toBe("0");

    act(() => {
      show.cb({ endCoordinates: { height: 291 } });
    });
    expect(readInset(tree)).toBe("291");

    act(() => {
      hide.cb({});
    });
    expect(readInset(tree)).toBe("0");

    act(() => {
      tree.unmount();
    });
  });

  it("treats a show event with no end frame as a zero inset", () => {
    let tree!: ReturnType<typeof render>;
    act(() => {
      tree = render(<Probe />);
    });
    const [show] = subs;

    act(() => {
      show.cb({});
    });
    expect(readInset(tree)).toBe("0");

    act(() => {
      tree.unmount();
    });
  });

  it("removes its subscriptions on unmount", () => {
    const removes: jest.Mock[] = [];
    (Keyboard.addListener as jest.Mock).mockImplementation(() => {
      const remove = jest.fn();
      removes.push(remove);
      return { remove };
    });

    let tree!: ReturnType<typeof render>;
    act(() => {
      tree = render(<Probe />);
    });
    act(() => {
      tree.unmount();
    });

    expect(removes).toHaveLength(2);
    for (const remove of removes) expect(remove).toHaveBeenCalledTimes(1);
  });
});
