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
