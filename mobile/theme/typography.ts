import { Platform } from 'react-native';

/**
 * Font-family token for the display (hero numeral / header) face.
 *
 * Currently resolves to the system font, which supports tabular numerals via
 * fontVariant: ['tabular-nums'] on iOS. Swap this constant to the licensed
 * geometric grotesque when it is bundled — all consumers update automatically.
 */
export const DISPLAY_FONT_FAMILY: string | undefined = Platform.select({
  ios: undefined,   // System SF Pro — supports tabular-nums natively on iOS
  android: undefined,
  default: undefined,
});

/** Standard body face — always the system font (SF Pro on iOS) for Dynamic Type. */
export const BODY_FONT_FAMILY: string | undefined = undefined;

/**
 * Typography scale. Sizes follow the iOS Dynamic Type size chart, plus three
 * Slacks-specific sizes (`title2Large`, `iconGlyph`, `detail`) that fill gaps
 * the Dynamic Type chart doesn't name but the app's own audited fontSize
 * literals need a home for. This is the single place a size is added — screen
 * stories reference these tokens, they never add new sizes to theme.
 */
export const typeScale = {
  heroDisplay: 56,
  largeTitle: 34,
  title1: 28,
  /** Between title2 and largeTitle — compact empty/gated-state headlines. */
  title2Large: 24,
  title2: 22,
  title3: 20,
  headline: 17,
  body: 17,
  /** Inline glyph-as-text sizing (e.g. a status/close glyph rendered as Text). */
  iconGlyph: 18,
  callout: 16,
  subhead: 15,
  /** Secondary/meta text between subhead and footnote (chips, row detail, chart axis labels). */
  detail: 14,
  footnote: 13,
  caption1: 12,
  caption2: 11,
} as const;

export type TypeScaleKey = keyof typeof typeScale;

/**
 * Header tracking (letter-spacing) for display / title contexts.
 * Tight tracking gives a confident, premium feel.
 */
export const displayTracking = -0.5;
