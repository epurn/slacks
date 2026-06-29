import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ProfileScreen } from "./ProfileScreen";
import type { ProfileDTO } from "@/api/profile";
import type { Session } from "@/state/session";

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

const SAVED_DTO: ProfileDTO = {
  user_id: SESSION!.userId,
  height_m: 1.75,
  weight_kg: 70,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "America/New_York",
  updated_at: "2026-06-26T00:00:00Z",
};

// SafeAreaProvider needs frame/insets metrics in a non-native test environment.
function render(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        {element}
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function findByA11yLabel(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (node) =>
      node.props.accessibilityLabel === label &&
      typeof node.props.onChangeText === "function",
  );
}

function pressByA11yLabel(tree: ReactTestRenderer, label: string) {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("ProfileScreen", () => {
  it("prompts sign-in when there is no session", () => {
    const tree = render(<ProfileScreen session={null} now={new Date("2026-06-26")} />);
    expect(textContent(tree)).toContain("Sign in to save your profile");
  });

  it("captures, converts, persists, and confirms a valid profile", async () => {
    const save = jest.fn().mockResolvedValue(SAVED_DTO);
    const tree = render(
      <ProfileScreen
        session={SESSION}
        save={save}
        now={new Date("2026-06-26")}
        timezone="America/New_York"
      />,
    );

    act(() => {
      findByA11yLabel(tree, "Height in centimetres").props.onChangeText("175");
      findByA11yLabel(tree, "Weight in kilograms").props.onChangeText("70");
      findByA11yLabel(tree, "Birth year").props.onChangeText("1990");
    });
    // Select the +5 formula variant (non-clinical label).
    pressByA11yLabel(
      tree,
      "Higher baseline (+5). Mifflin-St Jeor with the +5 constant — a higher resting estimate.",
    );

    await act(async () => {
      pressByA11yLabel(tree, "Save profile");
    });

    expect(save).toHaveBeenCalledTimes(1);
    const [, payload] = save.mock.calls[0];
    expect(payload).toEqual({
      height_m: 1.75,
      weight_kg: 70,
      birth_year: 1990,
      metabolic_formula: "mifflin_st_jeor_plus5",
      units_preference: "metric",
      timezone: "America/New_York",
    });
    expect(textContent(tree)).toContain("Profile saved");
  });

  it("blocks submission and shows errors when fields are missing", async () => {
    const save = jest.fn();
    const tree = render(
      <ProfileScreen session={SESSION} save={save} now={new Date("2026-06-26")} />,
    );

    await act(async () => {
      pressByA11yLabel(tree, "Save profile");
    });

    expect(save).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("Choose a calculation preference to continue.");
  });
});
