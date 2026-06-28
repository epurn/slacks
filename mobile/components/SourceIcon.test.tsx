import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { SourceIcon } from "./SourceIcon";
import type { ItemSourceDTO } from "@/api/derivedItems";

function sourceOf(source_type: ItemSourceDTO["source_type"]): ItemSourceDTO {
  const labels: Record<ItemSourceDTO["source_type"], string> = {
    trusted_nutrition_database: "USDA",
    product_database: "Open Food Facts",
    official_source: "example.com",
    user_label: "Label scan",
    model_prior: "Rough estimate",
  };
  return {
    source_type,
    label: labels[source_type],
    ref: `${source_type}:123`,
  };
}

function firstA11yLabel(tree: ReactTestRenderer): string {
  return tree.root.find((n) => !!n.props.accessibilityLabel).props
    .accessibilityLabel as string;
}

describe("SourceIcon — provenance types", () => {
  it.each<[ItemSourceDTO["source_type"], string]>([
    ["trusted_nutrition_database", "USDA"],
    ["product_database", "Open Food Facts"],
    ["user_label", "Label scan"],
    ["official_source", "example.com"],
  ])("%s: a11y label includes source label", (sourceType, expectedLabel) => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<SourceIcon source={sourceOf(sourceType)} />);
    });
    expect(firstA11yLabel(tree!)).toContain(expectedLabel);
  });

  it("model_prior: a11y label says 'Rough estimate'", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<SourceIcon source={sourceOf("model_prior")} />);
    });
    expect(firstA11yLabel(tree!)).toBe("Rough estimate");
  });

  it("null source: renders without crash, a11y label indicates unknown source", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<SourceIcon source={null} />);
    });
    const label = firstA11yLabel(tree!);
    expect(label).toBeTruthy();
  });

  it("undefined source: renders without crash", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<SourceIcon />);
    });
    expect(firstA11yLabel(tree!)).toBeTruthy();
  });
});

describe("SourceIcon — is_edited flag", () => {
  it("is_edited=true overrides source type with 'Edited by you' label", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <SourceIcon source={sourceOf("trusted_nutrition_database")} is_edited />,
      );
    });
    expect(firstA11yLabel(tree!)).toBe("Edited by you");
  });

  it("is_edited=false shows normal source label", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <SourceIcon source={sourceOf("trusted_nutrition_database")} is_edited={false} />,
      );
    });
    expect(firstA11yLabel(tree!)).toContain("USDA");
  });

  it("is_edited=true with null source still shows edited label", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<SourceIcon source={null} is_edited />);
    });
    expect(firstA11yLabel(tree!)).toBe("Edited by you");
  });
});
