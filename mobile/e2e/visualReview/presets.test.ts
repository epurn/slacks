/**
 * In-scope visual-review preset manifest tests (FTY-247).
 *
 * Proves every in-scope preset named in the story Scope is registered and, where
 * it seeds fixtures, that those fixtures reach the real API clients *through the
 * E2E mock fetch* (the same drift-guard approach launchMode.test.ts uses). Also
 * proves the deferred sub-state presets (owned by FTY-262..268) are NOT
 * registered here, so any such name fails closed.
 */

// Importing the barrel registers the in-scope preset manifest as a side effect.
import {
  activateVisualReviewPreset,
  getVisualReviewPreset,
  listVisualReviewPresetNames,
} from './index';
import { __deactivateVisualReview } from './session';
import { createE2EMockFetch } from '../launchMode';
import { E2E_RESOLVE_ITEM, E2E_SESSION } from '../fixtures';
import { toApiSession } from '@/state/session';
import { listTodayLogEventEntries } from '@/api/logEvents';
import { getDailySummary, getDailySummaryRange } from '@/api/dailySummary';
import { listWeightEntries } from '@/api/weightEntries';
import { getFoodSuggestions } from '@/api/foodSuggestions';
import { getProfile } from '@/api/profile';

const apiSession = toApiSession(E2E_SESSION);
const to = '2026-06-29';
const from = '2026-06-01';

afterEach(() => {
  __deactivateVisualReview();
});

const IN_SCOPE = [
  'today.populated',
  'today.meal',
  'today.empty',
  'today.suggestions',
  'today.signed_out',
  'trends.populated',
  'trends.imperial',
  'trends.empty',
  'weight.populated',
  'weight.empty',
  'settings.list',
] as const;

describe('in-scope preset manifest', () => {
  it('registers every in-scope preset named in Scope', () => {
    const names = listVisualReviewPresetNames();
    for (const name of IN_SCOPE) {
      expect(names).toContain(name);
      expect(getVisualReviewPreset(name)).toBeDefined();
    }
  });

  it('each preset carries a route + settledPath for the settle marker', () => {
    for (const name of IN_SCOPE) {
      const preset = getVisualReviewPreset(name)!;
      expect(typeof preset.route).toBe('string');
      expect(typeof preset.settledPath).toBe('string');
    }
  });
});

describe('today.populated seeds a resolved day through the real clients', () => {
  it('serves the multi-item day feed and a counting summary', async () => {
    activateVisualReviewPreset('today.populated', null);
    const mockFetch = createE2EMockFetch();
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(1);
    expect(entries[0]?.items[0]?.name).toBe(E2E_RESOLVE_ITEM.name);
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(true);
    expect(summary.intake.calories).toBe(245);
  });
});

describe('today.meal seeds a named multi-item meal (FTY-420)', () => {
  it('serves one multi-item event carrying a model-generated name', async () => {
    activateVisualReviewPreset('today.meal', null);
    const mockFetch = createE2EMockFetch();
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    // One event (the meal) with several derived items — the collapsed meal row.
    expect(entries).toHaveLength(1);
    expect(entries[0]?.items.length).toBeGreaterThan(1);
    expect(entries[0]?.event.name).toBe('Turkey sandwich');
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(true);
  });
});

describe('today.empty seeds the calm empty day', () => {
  it('serves an empty feed and a zero-intake summary', async () => {
    activateVisualReviewPreset('today.empty', null);
    const mockFetch = createE2EMockFetch();
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(0);
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.has_intake).toBe(false);
    expect(summary.intake.calories).toBe(0);
  });
});

describe('today.suggestions seeds the quick-add ranking through the real client', () => {
  it('serves a populated, ordered suggestion list on an empty day', async () => {
    activateVisualReviewPreset('today.suggestions', null);
    const mockFetch = createE2EMockFetch();
    const response = await getFoodSuggestions(apiSession, undefined, mockFetch);
    expect(response.items.length).toBeGreaterThan(1);
    // The saved food ranks first and carries a saved_food_id (estimator-skip path);
    // the row renders this exact server order.
    expect(response.items[0]?.saved_food_id).not.toBeNull();
    // The day itself stays empty so the shot focuses on the chips.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(0);
  });
});

describe('trends.populated / weight.populated ride the default populated fixtures', () => {
  it('leaves the weight series populated (no override)', async () => {
    activateVisualReviewPreset('trends.populated', null);
    const mockFetch = createE2EMockFetch();
    const entries = await listWeightEntries(apiSession, from, to, mockFetch);
    expect(entries.length).toBeGreaterThan(1);
  });
});

describe('trends.imperial serves an imperial profile through the real client (FTY-410)', () => {
  it('overrides units_preference to imperial while keeping the populated series', async () => {
    activateVisualReviewPreset('trends.imperial', null);
    const mockFetch = createE2EMockFetch();
    const profile = await getProfile(apiSession, mockFetch);
    expect(profile.units_preference).toBe('imperial');
    // The weight series is unchanged canonical kg — conversion is display-only.
    const entries = await listWeightEntries(apiSession, from, to, mockFetch);
    expect(entries.length).toBeGreaterThan(1);
  });
});

describe('trends.empty empties both Trends cards', () => {
  it('serves an empty weight series and an empty adherence range', async () => {
    activateVisualReviewPreset('trends.empty', null);
    const mockFetch = createE2EMockFetch();
    expect(await listWeightEntries(apiSession, from, to, mockFetch)).toHaveLength(0);
    expect(await getDailySummaryRange(apiSession, from, to, mockFetch)).toHaveLength(0);
  });
});

describe('weight.empty empties only the weight series', () => {
  it('serves an empty weight series but keeps the adherence range populated', async () => {
    activateVisualReviewPreset('weight.empty', null);
    const mockFetch = createE2EMockFetch();
    expect(await listWeightEntries(apiSession, from, to, mockFetch)).toHaveLength(0);
    // The adherence range keeps its default data — only the weight card is empty.
    expect(
      (await getDailySummaryRange(apiSession, from, to, mockFetch)).length,
    ).toBeGreaterThan(0);
  });
});

describe('deferred sub-state presets fail closed', () => {
  // These are owned by FTY-262..268 and must NOT be registered here.
  const DEFERRED = [
    'today.confirm_parsed',
    'correction.detail',
    'correction.typeahead',
    'trends.adherence_retry',
    'weight.sheet',
    'onboarding.goal',
    'settings.appearance',
    'capture.barcode_granted',
  ];

  it('are not registered, so lookup is undefined and activation returns false', () => {
    for (const name of DEFERRED) {
      expect(getVisualReviewPreset(name)).toBeUndefined();
      expect(activateVisualReviewPreset(name, null).ok).toBe(false);
    }
  });
});
