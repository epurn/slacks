/** Design token palettes — light and dark. Components read via useTheme(). */

export interface ColorPalette {
  /** Primary screen background. */
  readonly surface: string;
  /** Card / raised surface. */
  readonly surfaceRaised: string;
  /** Primary label text. */
  readonly text: string;
  /** Secondary label text — meets WCAG AA on surface. */
  readonly textSecondary: string;
  /** Muted / tertiary text — use only for decorative or large-text contexts. */
  readonly textMuted: string;
  /** Warm amber accent — use for decorative elements (bars, icons, highlights). */
  readonly accent: string;
  /** Text/icon colour to render ON TOP of the accent fill (e.g. a primary
   *  button label). Meets WCAG AA against `accent` in both light and dark. */
  readonly accentForeground: string;
  /** Amber safe for use as text — meets WCAG AA on both surfaces. */
  readonly accentText: string;
  /** Coral / over-budget colour — accent for the over-segment. */
  readonly coral: string;
  /** Hairline separator. */
  readonly separator: string;
  /** Background for buttons and input controls. */
  readonly controlBackground: string;
  /** Active segment icon / label tint in the floating switcher. */
  readonly tabActive: string;
  /** Inactive segment icon / label tint in the floating switcher — meets WCAG
   *  AA on the pill's glass/surface so inactive labels stay legible. */
  readonly tabInactive: string;
  /**
   * Translucent fill behind the floating switcher's blur material — the
   * token-sourced fallback so the pill stays legible where the native blur is
   * weak or unsupported (FTY-242).
   */
  readonly switcherGlass: string;
  /**
   * Hairline border for the floating switcher pill and its active capsule —
   * tuned separately from the general `separator` token so the pill's edge
   * stays crisp against a blurred, content-varying background (FTY-323).
   */
  readonly switcherBorder: string;
}

export const lightPalette: ColorPalette = {
  surface: '#F2F2F7',
  surfaceRaised: '#FFFFFF',
  text: '#1C1C1E',
  textSecondary: '#636366',
  textMuted: '#8E8E93',
  accent: '#E8960C',
  accentForeground: '#1C1C1E',
  accentText: '#92400E',
  coral: '#C0392B',
  separator: '#E5E5EA',
  controlBackground: '#E4E4EA',
  tabActive: '#1C1C1E',
  // Meets WCAG AA (≥4.5:1) on the pill's light glass/surface — #8E8E93 sat
  // below AA on the near-white switcher glass, so inactive labels were hard to
  // read (FTY-242 review). Shares the AA-verified secondary text tint.
  tabInactive: '#636366',
  switcherGlass: 'rgba(255,255,255,0.7)',
  switcherBorder: '#E5E5EA',
};

export const darkPalette: ColorPalette = {
  surface: '#1C1C1E',
  surfaceRaised: '#2C2C2E',
  text: '#F2F2F7',
  textSecondary: '#AEAEB2',
  textMuted: '#8E8E93',
  accent: '#F5A623',
  accentForeground: '#1C1C1E',
  accentText: '#F5A623',
  coral: '#FF6B6B',
  separator: '#38383A',
  controlBackground: '#3A3A3C',
  tabActive: '#F2F2F7',
  // Brightened from #8E8E93 (FTY-323): the switcher glass fill below was
  // deepened to separate the pill from the ~#1C1C1E canvas, which raises the
  // fill's own luminance. #AEAEB2 (shared with `textSecondary`) keeps ≥4.5:1
  // against the new fill composite — the old value would have dropped below
  // AA once the fill got lighter.
  tabInactive: '#AEAEB2',
  // Denser and visibly lighter than the ~#1C1C1E canvas (FTY-242's
  // rgba(28,28,30,0.55) was near-identical to the canvas and the pill
  // disappeared in dark mode — FTY-323). Paired with `switcherBorder` for a
  // crisp lit edge.
  switcherGlass: 'rgba(58,58,60,0.82)',
  switcherBorder: 'rgba(255,255,255,0.34)',
};
