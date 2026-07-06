/**
 * Root appearance controller.
 *
 * Reads the persisted appearance preference (Light / Dark / System) from the
 * on-device {@link AppSettingsStore} on boot, drives the root {@link ThemeProvider}'s
 * `override` from it, and exposes a setter so the Settings screen can switch the
 * live theme immediately. The Settings screen owns *persisting* the choice (it
 * writes the store); this provider owns only the in-memory override the theme
 * reads — so the chosen scheme is live on selection and restored on next launch.
 *
 * The store is injectable so it can be exercised without the platform filesystem.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { fileAppSettingsStore, type AppSettingsStore } from '@/state/appSettings';
import { ThemeProvider, type ColorSchemeOverride } from '@/theme';
import { useVisualReviewTheme } from '@/e2e/visualReview/hooks';

interface AppearanceControllerValue {
  /** Switch the live theme. Persisting the choice is the caller's responsibility. */
  readonly setAppearance: (v: ColorSchemeOverride) => void;
}

const AppearanceControllerContext = createContext<AppearanceControllerValue>({
  setAppearance: () => {},
});

/**
 * Wraps the app in a {@link ThemeProvider} whose override is hydrated from the
 * persisted appearance preference and can be changed live via
 * {@link useAppearanceController}.
 */
export function AppearanceProvider({
  children,
  store = fileAppSettingsStore,
}: {
  children?: ReactNode;
  store?: AppSettingsStore;
}) {
  const [override, setOverride] = useState<ColorSchemeOverride>('system');

  useEffect(() => {
    let active = true;
    void store.getAppearance().then((v) => {
      if (active) setOverride(v);
    });
    return () => {
      active = false;
    };
  }, [store]);

  const setAppearance = useCallback((v: ColorSchemeOverride) => {
    setOverride(v);
  }, []);

  // In an active visual-review preset (E2E only) the deep link's `theme` param
  // forces Light/Dark and wins over the persisted preference; `null` otherwise,
  // so release builds and normal use follow the stored Light/Dark/System choice.
  const visualReviewTheme = useVisualReviewTheme();
  const effectiveOverride: ColorSchemeOverride = visualReviewTheme ?? override;

  return (
    <AppearanceControllerContext.Provider value={{ setAppearance }}>
      <ThemeProvider override={effectiveOverride}>{children}</ThemeProvider>
    </AppearanceControllerContext.Provider>
  );
}

/** Access the appearance setter to switch the live theme from any screen. */
export function useAppearanceController(): AppearanceControllerValue {
  return useContext(AppearanceControllerContext);
}
