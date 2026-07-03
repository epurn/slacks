/**
 * FTY-225 barcode manual-entry flow: stateful mock transitions.
 *
 * Proves barcode-manual-entry.yaml's data path: the seeded "1 serving of greek
 * yogurt" phrase lands pending (skeleton), then a refresh GET serves the same
 * event completed with one resolved packaged-food item on the by-date feed and
 * a day summary that counts it. Keyed on its own raw_text, independent of the
 * resolve / correction / target / occlusion / clarify machines.
 *
 * Lives beside barcodeFixtures.ts (split from launchMode.test.ts to keep that
 * suite under the code-shape LOC threshold); drives the real API clients
 * through the mock like the launchMode.test.ts machines do.
 */

// jest.mock hoisted above imports (required by eslint-config-expo import/first rule).
jest.mock('@/state/onboardingComplete', () => ({
  markOnboardingComplete: jest.fn(),
  isOnboardingCompleteForUser: jest.fn(() => false),
  clearOnboardingComplete: jest.fn(),
}));

// eslint-disable-next-line import/first
import { createE2EMockFetch } from './launchMode';
// eslint-disable-next-line import/first
import { E2E_SESSION } from './fixtures';
// eslint-disable-next-line import/first
import {
  E2E_BARCODE_RAW_TEXT,
  E2E_BARCODE_EVENT_ID,
  E2E_BARCODE_ITEM,
} from './barcodeFixtures';
// eslint-disable-next-line import/first
import { toApiSession } from '@/state/session';
// eslint-disable-next-line import/first
import {
  createLogEvent,
  listTodayLogEvents,
  listTodayLogEventEntries,
} from '@/api/logEvents';
// eslint-disable-next-line import/first
import { getDailySummary } from '@/api/dailySummary';

describe('FTY-225 barcode manual-entry flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);

  it('POST the seeded barcode phrase returns a pending entry first', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_BARCODE_RAW_TEXT,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_BARCODE_EVENT_ID);
    expect(created.status).toBe('pending');
  });

  it('after refresh the feed carries the completed, counted packaged-food item', async () => {
    const mockFetch = createE2EMockFetch();
    // Before the log the item-forward feed is empty (empty day).
    expect(
      await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch),
    ).toHaveLength(0);
    await createLogEvent(apiSession, E2E_BARCODE_RAW_TEXT, undefined, mockFetch);
    // After the log, a pull-to-refresh GET sees the same event completed with
    // the resolved item — real serving data (1 serving) and barcode-lookup
    // provenance, the end state the flow asserts on-device.
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(1);
    expect(entries[0]?.event.id).toBe(E2E_BARCODE_EVENT_ID);
    expect(entries[0]?.event.status).toBe('completed');
    expect(entries[0]?.items).toHaveLength(1);
    expect(entries[0]?.items[0]?.name).toBe(E2E_BARCODE_ITEM.name);
    expect(entries[0]?.items[0]?.status).toBe('resolved');
    const item = entries[0]?.items[0];
    expect(item?.item_type === 'food' && item.amount).toBe(1);
    expect(item?.item_type === 'food' && item.unit).toBe('serving');
    // The plain event list also lists the completed entry so a poll keeps the row.
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_BARCODE_EVENT_ID);
    // The day totals count the resolved item — the "counted" half of the proof.
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.intake.calories).toBe(130);
  });

  it('the barcode branch does not disturb the clarify phase machine', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(apiSession, 'coffee', undefined, mockFetch);
    expect(created.status).toBe('needs_clarification');
  });
});
