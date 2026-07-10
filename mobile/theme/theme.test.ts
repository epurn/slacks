import React, { useEffect } from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { useTheme, ThemeProvider, lightPalette, darkPalette } from '@/theme';

// jest-expo's preset already mocks useColorScheme as a jest.fn() that returns
// 'light'. We obtain the typed mock handle so we can change its return value
// per test.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

// ---------------------------------------------------------------------------
// Helper component that captures theme values via effect (not during render)
// ---------------------------------------------------------------------------

type CaptureCallback = (theme: ReturnType<typeof useTheme>) => void;

function ThemeCapture({ onTheme }: { onTheme: CaptureCallback }): null {
  const theme = useTheme();
  // Capture the theme in an effect so we do not assign to an outer variable
  // during the render phase (avoids react-hooks/globals lint error).
  useEffect(() => {
    onTheme(theme);
  });
  return null;
}

function renderWithOverride(override?: 'light' | 'dark' | 'system'): ReturnType<typeof useTheme> {
  let captured: ReturnType<typeof useTheme> | null = null;
  const onTheme: CaptureCallback = (t) => { captured = t; };

  act(() => {
    const provider = override !== undefined
      ? React.createElement(ThemeProvider, { override }, React.createElement(ThemeCapture, { onTheme }))
      : React.createElement(ThemeProvider, {}, React.createElement(ThemeCapture, { onTheme }));
    create(provider);
  });

  if (captured === null) {
    throw new Error('ThemeCapture effect did not fire — check that act() flushes effects');
  }
  return captured;
}

// ---------------------------------------------------------------------------
// Contrast utility — WCAG relative luminance + contrast ratio
// ---------------------------------------------------------------------------

function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const linearize = (c: number): number =>
    c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

// Parses an `rgba(r,g,b,a)` string (the floating switcher's glass/border
// tokens) into its components.
function parseRgba(rgba: string): { r: number; g: number; b: number; a: number } {
  const match = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?\)/.exec(rgba);
  if (!match) throw new Error(`Not an rgba() string: ${rgba}`);
  return {
    r: Number(match[1]),
    g: Number(match[2]),
    b: Number(match[3]),
    a: match[4] !== undefined ? Number(match[4]) : 1,
  };
}

function toHex(r: number, g: number, b: number): string {
  const clamp = (c: number) => Math.max(0, Math.min(255, Math.round(c)));
  return `#${[r, g, b].map((c) => clamp(c).toString(16).padStart(2, '0')).join('')}`;
}

// Composites a translucent `rgba()` fill (or opaque hex) over an opaque hex
// background — the actual color a viewer sees where a token is layered over
// another, as opposed to the token's own value in isolation.
function compositeOver(fillColor: string, backgroundHex: string): string {
  if (!fillColor.startsWith('rgba') && !fillColor.startsWith('rgb')) return fillColor;
  const { r, g, b, a } = parseRgba(fillColor);
  const bg = backgroundHex.replace('#', '');
  const br = parseInt(bg.slice(0, 2), 16);
  const bg_ = parseInt(bg.slice(2, 4), 16);
  const bb = parseInt(bg.slice(4, 6), 16);
  return toHex(r * a + br * (1 - a), g * a + bg_ * (1 - a), b * a + bb * (1 - a));
}

// ---------------------------------------------------------------------------
// Theme accessor tests
// ---------------------------------------------------------------------------

describe('ThemeProvider — scheme resolution', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('resolves to lightPalette when override="light"', () => {
    const theme = renderWithOverride('light');
    expect(theme.colors).toEqual(lightPalette);
    expect(theme.isDark).toBe(false);
    expect(theme.scheme).toBe('light');
  });

  it('resolves to darkPalette when override="dark"', () => {
    const theme = renderWithOverride('dark');
    expect(theme.colors).toEqual(darkPalette);
    expect(theme.isDark).toBe(true);
    expect(theme.scheme).toBe('dark');
  });
});

// ---------------------------------------------------------------------------
// Override seam — explicit override wins over system scheme
// ---------------------------------------------------------------------------

describe('ThemeProvider — override seam', () => {
  it('picks lightPalette with override="light" even when system is dark', () => {
    mockUseColorScheme.mockReturnValue('dark');
    const theme = renderWithOverride('light');
    expect(theme.colors).toEqual(lightPalette);
    expect(theme.scheme).toBe('light');
  });

  it('picks darkPalette with override="dark" even when system is light', () => {
    mockUseColorScheme.mockReturnValue('light');
    const theme = renderWithOverride('dark');
    expect(theme.colors).toEqual(darkPalette);
    expect(theme.scheme).toBe('dark');
  });

  it('follows system when override="system" and system is light', () => {
    mockUseColorScheme.mockReturnValue('light');
    const theme = renderWithOverride('system');
    expect(theme.colors).toEqual(lightPalette);
    expect(theme.scheme).toBe('light');
  });

  it('follows system when override="system" and system is dark', () => {
    mockUseColorScheme.mockReturnValue('dark');
    const theme = renderWithOverride('system');
    expect(theme.colors).toEqual(darkPalette);
    expect(theme.scheme).toBe('dark');
  });
});

// ---------------------------------------------------------------------------
// Token contrast — WCAG AA (≥ 4.5:1 for normal text)
// ---------------------------------------------------------------------------

const WCAG_AA = 4.5;
// WCAG 1.4.11 non-text contrast threshold — used for graphical (non-text)
// distinguishing marks like the adherence ring and the switcher's pill border.
const WCAG_NON_TEXT = 3;

describe('lightPalette — WCAG AA token contrast on surface', () => {
  it('text (#1C1C1E) on surface (#F2F2F7) meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.text, lightPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('textSecondary (#636366) on surface (#F2F2F7) meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.textSecondary, lightPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('accentText (#92400E) on surface (#F2F2F7) meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.accentText, lightPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('accentForeground on accent fill (primary button label) meets 4.5:1', () => {
    expect(
      contrastRatio(lightPalette.accentForeground, lightPalette.accent),
    ).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

describe('darkPalette — WCAG AA token contrast on surface', () => {
  it('text (#F2F2F7) on surface (#1C1C1E) meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.text, darkPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('textSecondary (#AEAEB2) on surface (#1C1C1E) meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.textSecondary, darkPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('accentText (#F5A623) on surface (#1C1C1E) meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.accentText, darkPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('accentForeground on accent fill (primary button label) meets 4.5:1', () => {
    expect(
      contrastRatio(darkPalette.accentForeground, darkPalette.accent),
    ).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

// ---------------------------------------------------------------------------
// Floating switcher segment tints — WCAG AA (FTY-242, tightened FTY-323)
//
// The inactive tint renders directly over the switcher glass fill (composited
// over the screen's `surface` background, the worst case the blur can produce
// once native blur is factored out); the active tint renders over the opaque
// `surfaceRaised` capsule. FTY-323 deepened `switcherGlass` in dark mode so the
// pill visibly separates from the canvas — that raises the glass composite's
// own luminance, so the "glass is at least as dark as surface" shortcut this
// suite used to rely on no longer holds for dark. These tests check the tint
// against the *actual composited fill*, not the bare `surface` token.
// ---------------------------------------------------------------------------

describe('lightPalette — WCAG AA: floating switcher segment tints', () => {
  const glassComposite = compositeOver(lightPalette.switcherGlass, lightPalette.surface);

  it('tabInactive on the composited switcher glass meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.tabInactive, glassComposite)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('tabActive on surfaceRaised (the active capsule) meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.tabActive, lightPalette.surfaceRaised)).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

describe('darkPalette — WCAG AA: floating switcher segment tints', () => {
  const glassComposite = compositeOver(darkPalette.switcherGlass, darkPalette.surface);

  it('tabInactive on the composited switcher glass meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.tabInactive, glassComposite)).toBeGreaterThanOrEqual(WCAG_AA);
  });

  it('tabActive on surfaceRaised (the active capsule) meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.tabActive, darkPalette.surfaceRaised)).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

// ---------------------------------------------------------------------------
// Floating switcher pill separation from the canvas — WCAG non-text (FTY-323)
//
// The bug this story fixes: the dark `switcherGlass` fill used to be
// near-identical to the `#1C1C1E` canvas, so the pill visibly disappeared.
// These guard the fix at the token level: the composited glass fill and the
// pill's hairline border must each read as distinguishable (WCAG 1.4.11
// non-text, 3:1) from the canvas — actual visual separation is additionally
// proven by simulator evidence (see docs/verification/FTY-323).
// ---------------------------------------------------------------------------

describe('darkPalette — WCAG non-text: pill separates from the canvas (FTY-323)', () => {
  it('the composited switcherGlass fill is distinguishable from surface', () => {
    const composite = compositeOver(darkPalette.switcherGlass, darkPalette.surface);
    expect(contrastRatio(composite, darkPalette.surface)).toBeGreaterThan(1);
  });

  it('the composited switcherBorder hairline meets 3:1 against surface', () => {
    const composite = compositeOver(darkPalette.switcherBorder, darkPalette.surface);
    expect(contrastRatio(composite, darkPalette.surface)).toBeGreaterThanOrEqual(WCAG_NON_TEXT);
  });
});

// ---------------------------------------------------------------------------
// Trends headline delta + adherence cue — WCAG AA (FTY-189)
//
// The goal-aware headline delta (TrendsScreen.tsx) renders as `accentText`
// (already covered above — the "toward goal" state), `coral` (the "away from
// goal" state), or `textSecondary` (already covered — the neutral state), all
// as body text on `surface`. The adherence strip's off-target cue
// (AdherenceStrip.tsx) is a `surface`-colored ring on a `coral` fill — a
// graphical (non-text) distinguishing mark, so it is held to the WCAG 1.4.11
// non-text 3:1 threshold rather than the 4.5:1 text threshold.
// ---------------------------------------------------------------------------

describe('lightPalette — WCAG AA: headline delta "away from goal" state', () => {
  it('coral (#C0392B) on surface (#F2F2F7) meets 4.5:1', () => {
    expect(contrastRatio(lightPalette.coral, lightPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

describe('darkPalette — WCAG AA: headline delta "away from goal" state', () => {
  it('coral (#FF6B6B) on surface (#1C1C1E) meets 4.5:1', () => {
    expect(contrastRatio(darkPalette.coral, darkPalette.surface)).toBeGreaterThanOrEqual(WCAG_AA);
  });
});

describe('lightPalette — WCAG AA: off-target adherence cue (non-color ring)', () => {
  it('surface ring (#F2F2F7) on the coral off-target fill meets 3:1', () => {
    expect(contrastRatio(lightPalette.surface, lightPalette.coral)).toBeGreaterThanOrEqual(WCAG_NON_TEXT);
  });
});

describe('darkPalette — WCAG AA: off-target adherence cue (non-color ring)', () => {
  it('surface ring (#1C1C1E) on the coral off-target fill meets 3:1', () => {
    expect(contrastRatio(darkPalette.surface, darkPalette.coral)).toBeGreaterThanOrEqual(WCAG_NON_TEXT);
  });
});
