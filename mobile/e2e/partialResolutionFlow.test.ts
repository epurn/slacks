/**
 * FTY-330 partial-resolution E2E mock phase-machine tests.
 *
 * Kept out of `launchMode.test.ts` (which sits at its governance LOC baseline)
 * but exercises the same `createE2EMockFetch` binary. Proves the partial phase
 * machine that `partial-resolution.yaml` drives: submit → partially_resolved
 * (one committed sibling + one open question) → answer → completed in place.
 * Independent of the clarify phase machine (its own raw_text), so it never
 * collides in the shared binary. Each test builds a fresh mock so state does not
 * leak.
 */

// jest.mock hoisted above imports (eslint-config-expo import/first rule); the
// launchMode module imports onboardingComplete, mocked here to match the sibling
// suite and keep this unit test hermetic.
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
  E2E_PARTIAL_RAW_TEXT,
  E2E_PARTIAL_EVENT,
  E2E_PARTIAL_CLARIFICATION,
  E2E_PARTIAL_RESOLVED_ITEM,
  E2E_PARTIAL_HUMMUS_ITEM,
} from './partialResolutionFixtures';
// eslint-disable-next-line import/first
import { toApiSession } from '@/state/session';
// eslint-disable-next-line import/first
import {
  listTodayLogEvents,
  listTodayLogEventEntries,
  createLogEvent,
  getLogEventClarification,
  answerClarification,
} from '@/api/logEvents';
// eslint-disable-next-line import/first
import { getDailySummary } from '@/api/dailySummary';

describe('FTY-330 partial-resolution flow: stateful mock transitions', () => {
  const apiSession = toApiSession(E2E_SESSION);
  const questionId = E2E_PARTIAL_CLARIFICATION.questions[0]?.id ?? '';

  it('stage 0 → POST /log-events returns the partially_resolved event', async () => {
    const mockFetch = createE2EMockFetch();
    const created = await createLogEvent(
      apiSession,
      E2E_PARTIAL_RAW_TEXT,
      undefined,
      mockFetch,
    );
    expect(created.id).toBe(E2E_PARTIAL_EVENT.id);
    expect(created.status).toBe('partially_resolved');
    expect(created.raw_text).toBe(E2E_PARTIAL_RAW_TEXT);
  });

  it('stage 1 → by-date feed carries the committed sibling, clarification the open question', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_PARTIAL_RAW_TEXT, undefined, mockFetch);
    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries).toHaveLength(1);
    expect(entries[0]?.event.id).toBe(E2E_PARTIAL_EVENT.id);
    expect(entries[0]?.event.status).toBe('partially_resolved');
    // Exactly the committed sibling counts; the open component is not on the feed.
    expect(entries[0]?.items).toHaveLength(1);
    expect(entries[0]?.items[0]?.id).toBe(E2E_PARTIAL_RESOLVED_ITEM.id);

    const clarification = await getLogEventClarification(
      apiSession,
      E2E_PARTIAL_EVENT.id,
      mockFetch,
    );
    expect(clarification.questions).toHaveLength(1);
    expect(clarification.questions[0]?.text).toBe('How much hummus?');
    expect(clarification.questions[0]?.options).toEqual(['2 tbsp', '1/4 cup']);
  });

  it('stage 1 → GET /daily-summary counts the sibling and holds one uncounted unit', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_PARTIAL_RAW_TEXT, undefined, mockFetch);
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.intake.calories).toBe(140);
    expect(summary.uncounted_entries).toBe(1);
  });

  it('answering resolves the SAME event in place — no duplicate, phrase unchanged', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_PARTIAL_RAW_TEXT, undefined, mockFetch);
    const answered = await answerClarification(
      apiSession,
      E2E_PARTIAL_EVENT.id,
      questionId,
      '2 tbsp',
      mockFetch,
    );
    // The scoped re-estimate: same id, processing, raw phrase never mutated.
    expect(answered.id).toBe(E2E_PARTIAL_EVENT.id);
    expect(answered.status).toBe('processing');
    expect(answered.raw_text).toBe(E2E_PARTIAL_RAW_TEXT);
  });

  it('after answer → the same event completes in place with both siblings counted', async () => {
    const mockFetch = createE2EMockFetch();
    await createLogEvent(apiSession, E2E_PARTIAL_RAW_TEXT, undefined, mockFetch);
    await answerClarification(
      apiSession,
      E2E_PARTIAL_EVENT.id,
      questionId,
      '2 tbsp',
      mockFetch,
    );
    // Same event id, now completed — the committed sibling is unchanged and the
    // answered component has joined it as a second resolved row (no duplicate).
    const events = await listTodayLogEvents(apiSession, '2026-01-01', mockFetch);
    expect(events).toHaveLength(1);
    expect(events[0]?.id).toBe(E2E_PARTIAL_EVENT.id);
    expect(events[0]?.status).toBe('completed');

    const entries = await listTodayLogEventEntries(apiSession, '2026-01-01', mockFetch);
    expect(entries[0]?.items.map((item) => item.id)).toEqual([
      E2E_PARTIAL_RESOLVED_ITEM.id,
      E2E_PARTIAL_HUMMUS_ITEM.id,
    ]);

    // The open question is cleared and the day counts both siblings.
    const clarification = await getLogEventClarification(
      apiSession,
      E2E_PARTIAL_EVENT.id,
      mockFetch,
    );
    expect(clarification.questions).toHaveLength(0);
    const summary = await getDailySummary(apiSession, '2026-01-01', mockFetch);
    expect(summary.intake.calories).toBe(240);
    expect(summary.uncounted_entries).toBe(0);
  });
});
