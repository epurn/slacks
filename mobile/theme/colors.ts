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
  /** Tab bar active icon / tint. */
  readonly tabActive: string;
  /** Tab bar inactive icon / tint. */
  readonly tabInactive: string;
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
  tabInactive: '#8E8E93',
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
};
