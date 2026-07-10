/**
 * Settings sub-state visual-review seam (FTY-267).
 *
 * FTY-247's in-scope manifest (`e2e/visualReview/presets.ts`) only reaches the
 * settings route's top-level list (`settings.list`) — the goal editor, the body
 * metric editor, and the appearance control all sit behind either component-local
 * `useState` opened by a press callback (`editingGoal` / `editingBodyMetric`, see
 * `useSettingsController.ts`) or, for appearance, below the fold of the scroll
 * view. Reaching them for a screenshot needs a screen-owned seam, which this
 * module contributes **from the settings lane**, through FTY-247's public
 * registration API — no edits to the shared registry or manifest.
 *
 * Registration happens as an import side effect (mirroring how `presets.ts`
 * registers the in-scope manifest). This module is imported by
 * `useSettingsController.ts`, which every settings mount already pulls in via
 * `SettingsScreen.tsx` -> `app/profile.tsx` — and Expo Router's file-based routing
 * requires every file under `app/` at startup to build its route table, so the
 * registration runs before the `__visual-review` deep link can ever look these
 * names up, with no additional wiring in any shared or other-screen file.
 *
 * The edit-state presets reuse the same route/settledPath as `settings.list`
 * and the same default E2E fixtures (no `responses` overrides) — the sub-state
 * itself comes from `useSettingsVisualReviewSubState`, which the settings
 * controller and screen read to decide what to open. The target-override preset
 * stays at the top-level list but overrides only `GET /target` with a synthetic
 * user-source target so the user-override provenance label is visible without a
 * scripted tap.
 *
 * The read is a one-shot snapshot taken at mount (a plain `getVisualReviewCore()`
 * call inside a `useState` initializer), not a live subscription: "initial-state
 * seam" is the whole contract — once the settings screen has opened with the
 * requested sub-state, further changes are the user's own edits, not the
 * preset's. Outside E2E mode this always resolves to `null`, so no production
 * behaviour changes.
 */

import { useState } from 'react';

import { registerVisualReviewPreset } from '@/e2e/visualReview';
import type { VisualReviewFetchContext } from '@/e2e/visualReview';
import { getVisualReviewCore } from '@/e2e/visualReview/session';
import { isE2EMode } from '@/e2e/launchMode';
import { E2E_TARGET } from '@/e2e/fixtures';

/** The settings sub-state a visual-review preset can request. */
export type SettingsVisualReviewSubState =
  | 'goal_edit'
  | 'body_edit'
  | 'formula_edit'
  | 'appearance';

const SETTINGS_ROUTE = '/profile';

const SUBSTATE_BY_PRESET: Readonly<Record<string, SettingsVisualReviewSubState>> = {
  'settings.goal_edit': 'goal_edit',
  'settings.body_edit': 'body_edit',
  'settings.formula_edit': 'formula_edit',
  'settings.appearance': 'appearance',
};

const E2E_TARGET_WITH_USER_OVERRIDE = {
  ...E2E_TARGET,
  calories: {
    ...E2E_TARGET.calories,
    effective: E2E_TARGET.calories.derived + 150,
    source: 'user' as const,
  },
};

function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === 'GET' && ctx.pathEnd.endsWith(suffix);
}

for (const name of Object.keys(SUBSTATE_BY_PRESET)) {
  registerVisualReviewPreset({
    name,
    route: SETTINGS_ROUTE,
    settledPath: SETTINGS_ROUTE,
  });
}

registerVisualReviewPreset({
  name: 'settings.target_override',
  route: SETTINGS_ROUTE,
  settledPath: SETTINGS_ROUTE,
  responses: [{ match: get('/target'), body: E2E_TARGET_WITH_USER_OVERRIDE }],
});

/**
 * The settings sub-state the active visual-review preset requested at the
 * moment this settings screen mounted, or `null` (including every non-E2E
 * build, where this always resolves to `null` and the settings screen behaves
 * exactly as it does today).
 */
export function useSettingsVisualReviewSubState(): SettingsVisualReviewSubState | null {
  const [subState] = useState<SettingsVisualReviewSubState | null>(() => {
    if (!isE2EMode()) return null;
    return SUBSTATE_BY_PRESET[getVisualReviewCore().presetName ?? ''] ?? null;
  });
  return subState;
}
