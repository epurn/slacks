import { Text } from "react-native";

import type { ItemSourceDTO } from "@/api/derivedItems";
import { useTheme } from "@/theme";

/** Icon character + accessibility label for a given provenance. */
interface SourcePresentation {
  readonly glyph: string;
  readonly accessibilityLabel: string;
}

function presentationFor(
  source: ItemSourceDTO | null | undefined,
  is_edited: boolean,
): SourcePresentation {
  if (is_edited) {
    return { glyph: "✎", accessibilityLabel: "Edited by you" };
  }
  if (!source) {
    return { glyph: "·", accessibilityLabel: "Source unknown" };
  }
  switch (source.source_type) {
    case "trusted_nutrition_database":
      return { glyph: "🔍", accessibilityLabel: `Source: ${source.label}` };
    case "product_database":
      return { glyph: "📊", accessibilityLabel: `Source: ${source.label}` };
    case "user_label":
      return { glyph: "📷", accessibilityLabel: `Source: ${source.label}` };
    case "official_source":
      return { glyph: "🌐", accessibilityLabel: `Source: ${source.label}` };
    case "model_prior":
      return { glyph: "≈", accessibilityLabel: "Rough estimate" };
  }
}

/**
 * Always-on source provenance icon for a timeline item row (FTY-098).
 * Shows the FTY-092 source type as a small glyph with a VoiceOver label.
 * When `is_edited` is true, shows "✎" (edited icon) regardless of source type —
 * treated as just another provenance per the UX spec.
 */
export function SourceIcon({
  source,
  is_edited = false,
}: {
  source?: ItemSourceDTO | null;
  is_edited?: boolean;
}) {
  const { colors } = useTheme();
  const { glyph, accessibilityLabel } = presentationFor(source, is_edited);

  return (
    <Text
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
      style={{ fontSize: 13, color: colors.textMuted }}
    >
      {glyph}
    </Text>
  );
}
