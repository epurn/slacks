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
  tabInactive: '#8E8E93',
  switcherGlass: 'rgba(28,28,30,0.55)',
};
