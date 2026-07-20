/**
 * Cross-screen units-preference seam (FTY-410).
 *
 * The imperial/metric choice (FTY-021) is a display-only preference persisted on
 * the profile (`units_preference`); body values are always stored canonical (kg,
 * m). Trends — which renders the headline weight, chart Y-axis, and per-point
 * values converted from the canonical-kg series (FTY-070) — needs that
 * preference to pick lb vs kg, but it is not carried on the weight or
 * daily-summary read-models. This provider routes it through one value, exactly
 * like the goal-direction seam (state/goalDirection.tsx):
 *
 *   1. On sign-in / launch the provider **hydrates from the authoritative
 *      `GET /profile` read** (`units_preference`), so a returning user who chose
 *      imperial sees lb on Trends after a cold launch — not the metric default.
 *   2. `SettingsScreen` calls `setUnitsPreference` right after a successful units
 *      save (it receives the stored preference back on the `PUT /profile`
 *      response), so toggling Units in Settings and returning to Trends shows the
 *      new unit immediately — no stale metric render, no refetch. A same-session
 *      value is never clobbered by a slower hydrate.
 *
 * The value is in-memory and session-scoped — **not persisted to disk** — and
 * resets to the metric default on sign-out and when the signed-in user changes,
 * so a new account never inherits a stale preference. Consumers read the metric
 * default until the first known value arrives (the app's own default and what
 * the profile form seeds), so the fallback matches the rest of the app.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getProfile } from "@/api/profile";
import type { ApiSession } from "@/api/client";
import { toApiSession, useSession } from "@/state/session";
import type { UnitsPreference } from "@/state/profile";

/** The app-wide default when no preference is known yet (matches profile seed). */
const DEFAULT_UNITS_PREFERENCE: UnitsPreference = "metric";

export interface UnitsPreferenceController {
  /** The current display units — the metric default until a value is known. */
  readonly unitsPreference: UnitsPreference;
  setUnitsPreference(units: UnitsPreference): void;
  clearUnitsPreference(): void;
}

// Deliberately non-throwing defaults (unlike `useSessionController`): most
// screens don't need this value and shouldn't be forced to mount a provider (or
// update every existing test) just because it exists somewhere in the tree. The
// default resolves to metric, the app-wide default.
const UnitsPreferenceContext = createContext<UnitsPreferenceController>({
  unitsPreference: DEFAULT_UNITS_PREFERENCE,
  setUnitsPreference: () => {},
  clearUnitsPreference: () => {},
});

/** Default hydration read: the profile's stored `units_preference`. */
function readUnitsFromProfile(session: ApiSession): Promise<UnitsPreference> {
  return getProfile(session).then((profile) => profile.units_preference);
}

/**
 * Provides the session-scoped units preference to the tree. Mount once, near the
 * root (under `SessionProvider`, whose session it reads to hydrate).
 *
 * `readUnitsPreference` is injectable for tests; it defaults to the live
 * `GET /profile` read.
 */
export function UnitsPreferenceProvider({
  children,
  readUnitsPreference = readUnitsFromProfile,
}: {
  children: ReactNode;
  readUnitsPreference?: (session: ApiSession) => Promise<UnitsPreference | null>;
}) {
  // `null` means "not yet known" — consumers see the metric default until the
  // first real value (hydrate or an in-session set) arrives. Tracking the
  // unknown state lets the async hydrate below avoid clobbering a fresher set.
  const [unitsPreference, setUnitsPreferenceState] =
    useState<UnitsPreference | null>(null);
  const session = useSession();
  const userId = session?.userId ?? null;

  // Reset the known preference the instant the signed-in user changes (including
  // sign-out), so a prior account's preference never lingers before the async
  // hydrate below runs. Resetting during render — not in an effect — is React's
  // recommended way to adjust state on a prop/context change and avoids a stale
  // frame (https://react.dev/learn/you-might-not-need-an-effect).
  const [hydratedUserId, setHydratedUserId] = useState<string | null>(userId);
  if (userId !== hydratedUserId) {
    setHydratedUserId(userId);
    setUnitsPreferenceState(null);
  }

  const setUnitsPreference = useCallback((units: UnitsPreference) => {
    setUnitsPreferenceState(units);
  }, []);

  const clearUnitsPreference = useCallback(() => {
    setUnitsPreferenceState(null);
  }, []);

  // Hydrate from the authoritative `GET /profile` read whenever the signed-in
  // user changes. The preference was already reset above, so this only *seeds*
  // it — and only if nothing fresher was set this session (e.g. an in-session
  // units change via `setUnitsPreference`), so the hydrate never clobbers a
  // newer known value. A failed/absent read leaves it unknown (metric default).
  useEffect(() => {
    if (!session) return;
    let active = true;
    const apiSession = toApiSession(session);
    void readUnitsPreference(apiSession)
      .then((units) => {
        if (!active || units === null) return;
        setUnitsPreferenceState((prev) => (prev === null ? units : prev));
      })
      .catch(() => {
        // Best-effort: an unreachable read leaves the preference unknown rather
        // than guessing one, so the display stays on the metric default.
      });
    return () => {
      active = false;
    };
    // `userId` is the identity that gates a refetch; `session` is read inside.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, readUnitsPreference]);

  const value = useMemo<UnitsPreferenceController>(
    () => ({
      unitsPreference: unitsPreference ?? DEFAULT_UNITS_PREFERENCE,
      setUnitsPreference,
      clearUnitsPreference,
    }),
    [unitsPreference, setUnitsPreference, clearUnitsPreference],
  );

  return (
    <UnitsPreferenceContext.Provider value={value}>
      {children}
    </UnitsPreferenceContext.Provider>
  );
}

/** The current display units — the metric default until a value is known. */
export function useUnitsPreference(): UnitsPreference {
  return useContext(UnitsPreferenceContext).unitsPreference;
}

/** The full controller — `SettingsScreen` calls this after a units save. */
export function useUnitsPreferenceController(): UnitsPreferenceController {
  return useContext(UnitsPreferenceContext);
}
